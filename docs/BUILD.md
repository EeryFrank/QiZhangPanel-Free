# 从源码构建

需要 Windows x64、.NET Framework 4.8 编译器、Python 3.13 和 JDK 17 或更高版本。构建只使用公开源码和公开下载的运行组件。

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-free.ps1 `
  -CacheDirectory "$env:LOCALAPPDATA\QiZhangPanelFreeBuild\cache" `
  -OutputDirectory .\artifacts `
  -Python python `
  -JdkHome $env:JAVA_HOME
```

`-ExecutionPolicy Bypass` 仅对这一构建进程生效，不修改系统策略。请先阅读脚本，只运行你信任的源码。

构建入口固定生成免费版，不需要选择产品档位。`-RuntimeArchive` 可指定已有的 Python 嵌入式运行时 ZIP，脚本仍会检查固定 SHA-256；省略时按脚本中的官方地址下载。缓存目录与产物目录均可自定义，源码不依赖开发者电脑上的磁盘路径。

Java 命令桥接工具从仓库源码构建，目标兼容 Java 8 字节码；JDK 是构建工具，服务端实际运行版本仍由其核心决定。不要把旧构建 JAR 当作源码的替代。

## 验证

```powershell
python -B -m unittest discover -s tests -p "test_*.py"
python -B scripts/audit-public-tree.py
```

代码审计只提供模式检查和发布文件边界检查，不能替代人工审阅。涉及 Windows 窗口、进程、控制台及文件操作的修改，还应使用隔离目录实际验证。

发布前保留完整 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和运行时原始许可证，生成所有交付文件的 SHA-256。不要提交运行时缓存、安装目录、账号数据、服务器文件或构建日志。
