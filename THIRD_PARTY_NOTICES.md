# 第三方组件

七章控制面板免费版的原创代码和本仓库提供的图标由 EeryFrank 发布。项目许可证不替代任何第三方组件的许可证或商标权利。

| 组件 | 使用与许可 |
| --- | --- |
| Python 3.13.15 Windows embeddable x64 | 发行包放在 `runtime` 中，保留原始 `runtime/LICENSE.txt`。该文件包含 PSF、历史 Python 许可及随 Python 分发组件的声明。Python、OpenSSL、运行库等文件不能统一标成面板原创 GPL 代码。 |
| Microsoft .NET Framework 4.8 / Windows Forms | 使用 Windows 上安装的系统组件；本项目不随包重新分发 .NET Framework 安装程序。 |
| JDK / Java 标准库 | 构建命令桥接工具时使用，用户运行 Java 服务端时按核心要求自行提供。发行包不捆绑 JDK、Minecraft 核心或其类库。 |

Python 原始运行时 ZIP 的 SHA-256：`d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf`。构建脚本校验此摘要，并把原始许可证复制进发行包。命令桥接工具的项目源码随本仓库提供。

Minecraft 服务端、Java、插件、模组和用户导入的整合包分别遵循其供应方的许可证及使用条件。面板的 GPL 许可证不授予这些内容的额外权利，也不替代 Minecraft EULA。

Python 官方发行页：<https://www.python.org/downloads/release/python-31315/>。

© 2026 [EeryFrank](https://github.com/EeryFrank)
