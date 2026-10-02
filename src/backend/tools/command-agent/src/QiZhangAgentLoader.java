/*
 * Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
 * Java 8-compatible helper; CLI stays compatible with five panel arguments.
 */
import java.io.File;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.util.Properties;
import java.util.UUID;

public final class QiZhangAgentLoader {
    private QiZhangAgentLoader() {}

    public static void main(String[] arguments) {
        Object machine = null;
        Class<?> virtualMachine = null;
        boolean queued = false;
        boolean loadAttempted = false;
        String stage = "helper";
        try {
            // Python consumes this helper as UTF-8 even on Java 8/GBK Windows.
            // This changes only the short-lived helper, never the game JVM.
            System.setOut(new PrintStream(System.out, true, "UTF-8"));
            System.setErr(new PrintStream(System.err, true, "UTF-8"));
            virtualMachine = Class.forName("com.sun.tools.attach.VirtualMachine");
            if (arguments.length == 1 && "--probe".equals(arguments[0])) {
                virtualMachine.getMethod("attach", String.class);
                virtualMachine.getMethod("loadAgent", String.class, String.class);
                System.out.println("QIZHANG_ATTACH_AVAILABLE");
                return;
            }
            if (arguments.length != 5 || !arguments[0].matches("[1-9][0-9]*")) {
                throw new IllegalArgumentException("Usage: QiZhangAgentLoader <pid> <agent-jar> "
                    + "<base64-command> <base64-expected-root> <expected-os-start-ms>");
            }
            QiZhangBukkitCommandAgentV3.validateCommand(QiZhangBukkitCommandAgentV3.decode(arguments[2]));
            File expectedRoot = new File(QiZhangBukkitCommandAgentV3.decode(arguments[3])).getCanonicalFile();
            if (!expectedRoot.isDirectory()) throw new IllegalArgumentException("Expected server directory does not exist");
            long expectedStart = Long.parseLong(arguments[4]);
            if (expectedStart <= 0) throw new IllegalArgumentException("Expected OS creation time must be positive");
            File jar = new File(arguments[1]).getCanonicalFile();
            if (!jar.isFile()) throw new IllegalArgumentException("Command agent JAR does not exist");
            String nonce = UUID.randomUUID().toString().replace("-", "");
            String body = "qzb3." + arguments[3] + "." + expectedStart + "."
                + arguments[0] + "." + nonce + "." + arguments[2];
            String payload = body + "." + QiZhangBukkitCommandAgentV3.digest(body);
            stage = "attach";
            machine = virtualMachine.getMethod("attach", String.class).invoke(null, arguments[0]);
            stage = "identity";
            Properties properties = (Properties) virtualMachine.getMethod("getSystemProperties").invoke(machine);
            String actualRoot = properties.getProperty("user.dir");
            if (actualRoot == null || !expectedRoot.equals(new File(actualRoot).getCanonicalFile())) {
                throw new IllegalStateException("Target JVM directory differs from the selected server");
            }
            stage = "agent_load";
            Throwable loadFailure = null;
            loadAttempted = true;
            try {
                virtualMachine.getMethod("loadAgent", String.class, String.class).invoke(
                    machine, jar.getPath(), payload);
            } catch (Throwable error) {
                loadFailure = unwrap(error);
            }
            stage = "receipt";
            properties = (Properties) virtualMachine.getMethod("getSystemProperties").invoke(machine);
            String[] values = properties.getProperty(
                QiZhangBukkitCommandAgentV3.RESULT_PROPERTY, "").split("\\|", -1);
            if (values.length != 3 || !nonce.equals(values[0])) {
                throw new UnconfirmedException("No matching V3 agent receipt; stage=agent_load"
                    + (loadFailure == null ? "" : "; " + describe(loadFailure)));
            }
            String detail = QiZhangBukkitCommandAgentV3.decode(values[2]);
            if ("QUEUED".equals(values[1])) {
                // The target receipt is authoritative, including when a newer
                // helper rejects the legacy target's bare "0" attach reply.
                queued = true;
            } else if ("REJECTED".equals(values[1])) {
                throw new RejectedException(detail);
            } else {
                throw new UnconfirmedException(detail);
            }
        } catch (Throwable error) {
            Throwable cause = unwrap(error);
            boolean rejected = cause instanceof RejectedException || !loadAttempted;
            String detail = cause instanceof RejectedException || cause instanceof UnconfirmedException
                ? cause.getMessage() : "stage=" + stage + ": " + describe(cause);
            System.err.println((rejected ? "QIZHANG_COMMAND_REJECTED: " : "QIZHANG_COMMAND_UNCONFIRMED: ") + detail);
            if (!rejected) {
                System.err.println("The command may have been accepted. Inspect server state; do not automatically resend.");
            }
        } finally {
            if (machine != null && virtualMachine != null) {
                try {
                    virtualMachine.getMethod("detach").invoke(machine);
                } catch (Throwable ignored) {
                    // An accepted stop may already be terminating this JVM.
                }
            }
        }
        if (queued) {
            System.out.println("QIZHANG_COMMAND_QUEUED");
        } else {
            System.exit(2);
        }
    }

    private static Throwable unwrap(Throwable error) {
        while (error instanceof InvocationTargetException
            && ((InvocationTargetException) error).getCause() != null) {
            error = ((InvocationTargetException) error).getCause();
        }
        return error;
    }

    private static String describe(Throwable error) {
        return error.getClass().getSimpleName() + ": "
            + (error.getMessage() == null ? "no detail" : error.getMessage());
    }

    private static final class RejectedException extends Exception {
        RejectedException(String message) { super(message); }
    }

    private static final class UnconfirmedException extends Exception {
        UnconfirmedException(String message) { super(message); }
    }
}
