/*
 * Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
 * One-shot console queue agent. The panel retains and validates the native
 * Windows process handle. OS creation time is not the JVM initialization time.
 * No background thread, direct Bukkit command dispatch, file, port, or retry.
 */
import java.io.File;
import java.lang.instrument.Instrumentation;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.lang.management.ManagementFactory;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

public final class QiZhangBukkitCommandAgentV3 {
    static final String RESULT_PROPERTY = "qizhang.command.v3.result";
    private QiZhangBukkitCommandAgentV3() {}

    public static void agentmain(String arguments, Instrumentation instrumentation) {
        String nonce = null;
        String stage = "payload";
        boolean invokingQueue = false;
        try {
            String[] parts = arguments == null ? new String[0] : arguments.split("\\.", -1);
            if (parts.length > 4 && parts[4].matches("[0-9a-f]{32}")) {
                nonce = parts[4];
            }
            if (parts.length != 7 || !"qzb3".equals(parts[0]) || nonce == null
                || !parts[6].matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException(
                    "Incomplete request; the legacy attach transport may have truncated its payload"
                );
            }
            String body = arguments.substring(0, arguments.lastIndexOf('.'));
            if (!MessageDigest.isEqual(digest(body).getBytes(StandardCharsets.US_ASCII),
                parts[6].getBytes(StandardCharsets.US_ASCII))) {
                throw new IllegalArgumentException("Request integrity check failed");
            }
            stage = "identity";
            File expectedRoot = new File(decode(parts[1])).getCanonicalFile();
            String currentDirectory = System.getProperty("user.dir");
            if (!expectedRoot.isDirectory() || currentDirectory == null
                || !expectedRoot.equals(new File(currentDirectory).getCanonicalFile())) {
                throw new IllegalStateException("Target JVM directory differs from the selected server");
            }
            long expectedOsTime = Long.parseLong(parts[2]);
            long expectedPid = Long.parseLong(parts[3]);
            String runtimePid = ManagementFactory.getRuntimeMXBean().getName().split("@", 2)[0];
            if (expectedOsTime <= 0 || expectedPid <= 0 || !runtimePid.matches("[1-9][0-9]*")
                || expectedPid != Long.parseLong(runtimePid)) {
                throw new IllegalStateException("Target JVM PID differs from the selected process");
            }
            // Caller verifies OS creation through its retained native handle.
            // RuntimeMXBean.getStartTime() denotes a different event.
            stage = "command";
            String command = decode(parts[5]);
            validateCommand(command);
            stage = "lookup";
            Object server = findServer(instrumentation);
            stage = "queue_lookup";
            MethodHandle queue = findQueue(server);
            stage = "queue";
            invokingQueue = true;
            queue.invokeWithArguments(command);
            publish(nonce, "QUEUED", "stage=queued: Accepted by the server console queue");
        } catch (Throwable error) {
            String status = invokingQueue ? "UNCONFIRMED" : "REJECTED";
            String message = "stage=" + stage + ": " + describe(error);
            if (nonce != null) {
                publish(nonce, status, message);
            }
            System.err.println("[QiZhang command agent V3] " + status + ": " + message);
            throw new IllegalStateException(message, error);
        }
    }

    static String decode(String encoded) throws Exception {
        return StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(Base64.getDecoder().decode(encoded))).toString();
    }

    static String digest(String text) throws Exception {
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        char[] hex = "0123456789abcdef".toCharArray();
        StringBuilder result = new StringBuilder(64);
        for (byte value : bytes) {
            result.append(hex[(value & 255) >>> 4]).append(hex[value & 15]);
        }
        return result.toString();
    }

    static void validateCommand(String command) {
        if (command == null || command.trim().isEmpty() || command.length() > 2000
            || command.indexOf('\0') >= 0 || command.indexOf('\r') >= 0 || command.indexOf('\n') >= 0) {
            throw new IllegalArgumentException("Command must be one nonempty line of at most 2000 characters");
        }
    }

    private static void publish(String nonce, String status, String message) {
        String bounded = message.replace('\0', ' ').replace('\r', ' ').replace('\n', ' ');
        if (bounded.length() > 1800) bounded = bounded.substring(0, 1800);
        System.setProperty(RESULT_PROPERTY, nonce + "|" + status + "|"
            + Base64.getEncoder().encodeToString(bounded.getBytes(StandardCharsets.UTF_8)));
    }

    private static String describe(Throwable error) {
        String text = error.getClass().getSimpleName() + ": " + error.getMessage();
        Throwable cause = error.getCause();
        if (cause != null && cause != error) {
            text += " (" + cause.getClass().getSimpleName() + ": " + cause.getMessage() + ")";
        }
        return text;
    }

    private static Object findServer(Instrumentation instrumentation) throws Throwable {
        Object found = null;
        StringBuilder rejected = new StringBuilder();
        int count = 0;
        for (Class<?> candidate : instrumentation.getAllLoadedClasses()) {
            boolean bukkit = "org.bukkit.Bukkit".equals(candidate.getName());
            boolean forge = "net.minecraftforge.server.ServerLifecycleHooks".equals(candidate.getName());
            if (!bukkit && !forge) continue;
            count++;
            try {
                Object server;
                if (forge) {
                    Class<?> api = Class.forName("net.minecraft.server.MinecraftServer", false,
                        candidate.getClassLoader());
                    server = MethodHandles.lookup().in(candidate).findStatic(candidate, "getCurrentServer",
                        MethodType.methodType(api)).invokeWithArguments();
                    if (server == null) continue;
                    if (!knownDedicatedServer(server)) {
                        throw new IllegalStateException("Forge hook has no recognized DedicatedServer instance");
                    }
                } else {
                Class<?> api = Class.forName("org.bukkit.Server", false, candidate.getClassLoader());
                // Anchor resolution to each candidate's own loader. Java 8's
                // bootstrap publicLookup can impose cross-loader constraints
                // when several loaded Bukkit API copies have the same names.
                Object craft = MethodHandles.lookup().in(candidate).findStatic(
                    candidate, "getServer", MethodType.methodType(api)).invokeWithArguments();
                if (craft == null) continue;
                if (!craft.getClass().getName().startsWith("org.bukkit.craftbukkit.")) {
                    throw new IllegalStateException("Bukkit instance is not a recognized CraftServer");
                }
                server = findNativeServer(craft);
                }
                if (found != null && found != server) throw new AmbiguousServerException();
                found = server;
            } catch (AmbiguousServerException ambiguity) {
                throw ambiguity;
            } catch (Throwable invalidCandidate) {
                rethrowFatal(invalidCandidate);
                if (rejected.length() < 1000) {
                    rejected.append(" [").append(candidate.getName()).append(" candidate ").append(count).append(": ")
                        .append(describe(invalidCandidate)).append("]");
                }
            }
        }
        if (found == null) {
            throw new IllegalStateException("No supported running Bukkit/CatServer/Forge instance was found; candidates="
                + count + rejected.toString());
        }
        return found;
    }

    private static Object findNativeServer(Object craft) throws Throwable {
        Class<?> concrete = craft.getClass();
        ClassLoader loader = concrete.getClassLoader();
        String version = concrete.getPackage().getName().substring("org.bukkit.craftbukkit".length());
        String[] types = {"net.minecraft.server.MinecraftServer", "net.minecraft.server.dedicated.DedicatedServer",
            "net.minecraft.server" + version + ".MinecraftServer",
            "net.minecraft.server" + version + ".DedicatedServer"};
        Throwable last = null;
        for (String name : types) {
            try {
                Class<?> returnType = Class.forName(name, false, loader);
                MethodHandle getter = MethodHandles.lookup().in(concrete).findVirtual(
                    concrete, "getServer", MethodType.methodType(returnType));
                Object server = getter.invokeWithArguments(craft);
                if (!knownDedicatedServer(server)) {
                    throw new IllegalStateException("CraftServer getter has no recognized DedicatedServer instance");
                }
                return server;
            } catch (ClassNotFoundException missingType) {
                last = missingType;
            } catch (NoSuchMethodException missingMethod) {
                last = missingMethod;
            }
        }
        throw new IllegalStateException("No supported CraftServer.getServer() signature in " + concrete.getName(), last);
    }

    private static boolean knownDedicatedServer(Object instance) {
        if (instance == null) return false;
        for (Class<?> type = instance.getClass(); type != null; type = type.getSuperclass()) {
            String name = type.getName();
            if ("net.minecraft.server.dedicated.DedicatedServer".equals(name)
                || name.matches("net\\.minecraft\\.server\\.v[0-9]+_[0-9]+_R[0-9]+\\.DedicatedServer")) return true;
        }
        return false;
    }

    private static MethodHandle findQueue(Object server) throws Throwable {
        Class<?> concrete = server.getClass();
        ClassLoader loader = concrete.getClassLoader();
        String bukkitSender = null;
        for (Class<?> type = concrete; type != null; type = type.getSuperclass()) {
            if (type.getName().matches("net\\.minecraft\\.server\\.v[0-9]+_[0-9]+_R[0-9]+\\.DedicatedServer")) {
                bukkitSender = type.getPackage().getName() + ".ICommandListener";
                break;
            }
        }
        String[][] signatures = {{"func_71331_a", "net.minecraft.command.ICommandSender"},
            {"issueCommand", "net.minecraft.command.ICommandSender"}, {"issueCommand", bukkitSender}};
        for (String[] signature : signatures) {
            if (signature[1] == null) continue;
            try {
                Class<?> sender = Class.forName(signature[1], false, loader);
                if (!sender.isInstance(server)) continue;
                // Exact lookup avoids resolving unrelated missing signature types.
                // SRG takes precedence if the server also exposes a Bukkit alias.
                MethodHandle queue = MethodHandles.lookup().in(concrete).findVirtual(concrete, signature[0],
                    MethodType.methodType(void.class, String.class, sender)).bindTo(server);
                return MethodHandles.insertArguments(queue, 1, server);
            } catch (ClassNotFoundException missingType) {
                // Try the next explicitly known console queue signature.
            } catch (NoSuchMethodException missingMethod) {
                // No invocation has occurred; a safe lookup fallback is possible.
            }
        }
        // Forge 1.20.1's original console thread uses this same queue. The
        // constructor creates a synchronized pending list; server tick drains it.
        // Resolving Commands.performPrefixedCommand and calling it on the attach
        // thread would bypass the main thread, so deliberately do not do that.
        try {
            Class<?> sourceType = Class.forName("net.minecraft.commands.CommandSourceStack", false, loader);
            for (String queueName : new String[]{"m_139645_", "handleConsoleInput"}) {
                MethodHandle queue;
                try {
                    queue = MethodHandles.lookup().in(concrete).findVirtual(concrete, queueName,
                        MethodType.methodType(void.class, String.class, sourceType)).bindTo(server);
                } catch (NoSuchMethodException absent) {
                    continue;
                }
                for (String getterName : new String[]{"m_129893_", "createCommandSourceStack"}) {
                    MethodHandle getter;
                    try {
                        getter = MethodHandles.lookup().in(concrete).findVirtual(concrete, getterName,
                            MethodType.methodType(sourceType));
                    } catch (NoSuchMethodException absent) {
                        continue;
                    }
                    Object source = getter.invokeWithArguments(server);
                    if (source == null) throw new IllegalStateException("Console command source is unavailable");
                    return MethodHandles.insertArguments(queue, 1, source);
                }
            }
        } catch (ClassNotFoundException absent) {
            // Older Bukkit servers lack the modern console source type.
        }
        throw new IllegalStateException("No supported console queue signature on " + concrete.getName());
    }

    private static void rethrowFatal(Throwable error) {
        if (error instanceof VirtualMachineError) throw (VirtualMachineError) error;
        if (error instanceof ThreadDeath) throw (ThreadDeath) error;
    }

    private static final class AmbiguousServerException extends IllegalStateException {
        AmbiguousServerException() { super("More than one distinct running server instance is loaded"); }
    }
}
