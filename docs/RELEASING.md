# 发布免费版

构建脚本只准备本地产物。上传、推送标签和创建正式 Release 由维护者在确认需要发布时执行，不会随着普通构建自动发生。

## 固定下载入口

网站使用以下链接，无需在每次更新后改版本号：

- GitHub：`https://github.com/EeryFrank/QiZhangPanel-Free/releases/latest/download/qizhang-panel-free-setup.exe`
- GitLab：`https://gitlab.com/EeryFrank/QiZhangPanel-Free/-/releases/permalink/latest/downloads/qizhang-panel-free-setup.exe`

**每个新的正式 Release 必须包含 `qizhang-panel-free-setup.exe`。** 仅上传带版本号的文件，会使最新版本的固定入口失效。别名属于各自的 Release：新版本上传到新标签下面，旧标签里的文件继续保留。GitLab 还必须配置相应的资产直链路径，只有显示名称相同并不足够。

历史例外：2.5.7 的固定别名在原发行完成后补充，使用单独的 `SHA256SUMS-latest.txt` 校验，原 `SHA256SUMS.txt` 保持不变。后续构建会将固定别名直接纳入总清单。

## 发布前

1. 核对版本、变更记录及测试结果，完成源码审计和实际安装验证。确认工作区没有待发布的未提交修改。
2. 使用独立产物目录构建，不混入其他版本的 EXE/ZIP。保留完整许可证和第三方说明。
3. 检查四个发布附件：`qizhang-panel-free-X.Y.Z-setup.exe`、`qizhang-panel-free-X.Y.Z-portable.zip`、`qizhang-panel-free-setup.exe`、`SHA256SUMS.txt`。两个 EXE 的 SHA-256 必须相同，清单须包含全部三个二进制附件。
4. 取得用户对本次发布的授权后，再推送已审阅源码及 `vX.Y.Z` 标签到两站。两站同名标签必须指向同一预期提交；标记已有但提交不同应停止处理，不能强推或改写标签。

可使用以下只读命令核对标签；注解标签以 `^{}` 行的提交为准，轻量标签使用普通行：

```powershell
git rev-parse 'vX.Y.Z^{commit}'
git ls-remote origin 'refs/tags/vX.Y.Z' 'refs/tags/vX.Y.Z^{}'
git ls-remote gitlab 'refs/tags/vX.Y.Z' 'refs/tags/vX.Y.Z^{}'
```

不要将 `X.Y.Z` 原样用于发行。重复发布之前先列出现有资产并下载核对：已存在且哈希相同的文件可以保留；同名但内容不同则停止，使用新的版本号重新发行。不要自动覆盖、删除重传已有版本文件，也不要使用 GitHub CLI 的 `--clobber`。

## GitHub

先为已经存在于远端的标签建立草稿 Release，再上传四个附件。以下是明确授权发布之后的操作示例；`$version`、`$artifactDirectory`、`$releaseNotes` 均应指向本次已验证内容：

```powershell
$tag = "v$version"
$assets = @(
    "qizhang-panel-free-$version-setup.exe",
    "qizhang-panel-free-$version-portable.zip",
    'qizhang-panel-free-setup.exe',
    'SHA256SUMS.txt'
) | ForEach-Object { Join-Path $artifactDirectory $_ }
gh release create $tag --repo EeryFrank/QiZhangPanel-Free --verify-tag --draft --title $tag --notes-file $releaseNotes
if ($LASTEXITCODE -ne 0) { throw 'Release creation failed; inspect existing release before retrying.' }
gh release upload $tag @assets --repo EeryFrank/QiZhangPanel-Free
if ($LASTEXITCODE -ne 0) { throw 'Upload incomplete; do not publish the draft.' }
```

检查草稿资产完整后发布正式版本，再检查 `latest` 确实指向本次版本。不要将测试版作为网站的正式下载入口。`--verify-tag` 和不使用 `--clobber` 的行为见 [GitHub 创建 Release](https://cli.github.com/manual/gh_release_create) 与 [上传附件](https://cli.github.com/manual/gh_release_upload)。

## GitLab

先把相同四份文件上传到本项目 Generic Package Registry 的独立版本目录，例如 `qizhang-panel-free/X.Y.Z/`。上传前检查该版本目录：已有文件必须核对哈希，禁止写入不同内容的重复文件。不要使用一个跨版本共用的 `latest` 包目录覆盖旧文件。

确认远端标签后创建相应 Release，为四份文件分别添加资产链接。每个链接的 `url` 指向该版本的实际 Package Registry 下载地址；设置 `link_type` 为 `package`。固定安装别名必须使用以下字段：

```json
{
  "name": "qizhang-panel-free-setup.exe",
  "url": "<本项目本版本包目录中的 qizhang-panel-free-setup.exe 下载地址>",
  "direct_asset_path": "/qizhang-panel-free-setup.exe",
  "link_type": "package"
}
```

另外三个附件也设置 `direct_asset_path` 为 `/` 加完整文件名。这样可以通过当前标签的 `/-/releases/vX.Y.Z/downloads/<文件名>` 直接验证全部附件。最新 Release 必须是已验证的正式版本，并检查其发布时间；不要让尚未验证的测试发行占用网站入口。

接口字段和永久直链规则见 [GitLab Release links API](https://docs.gitlab.com/api/releases/links/) 与 [Release 资产永久链接](https://docs.gitlab.com/user/project/releases/release_fields/#permanent-links-to-latest-release-assets)。认证凭据只保存在维护者的本机凭据管理或受保护的 CI Secret 中，不放进下载地址、源码或日志。

## 发布后验收

以不携带账号、Cookie 或令牌的请求验证公开下载。先分别从两站的指定标签下载四份附件；把三个二进制文件的大小和 SHA-256 与本地发行文件、清单逐项比较，并核对两站清单内容一致。只检查 HTTP 状态或文件名不足以证明下载正确。

随后分别下载本页开头两条固定入口链接，检查其内容与本版本的安装 EXE 完全相同。以下只读示例验证固定入口；临时目录由运行者指定：

```powershell
$installer = Join-Path $artifactDirectory "qizhang-panel-free-$version-setup.exe"
$expected = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
$downloadLinks = @{
    github = 'https://github.com/EeryFrank/QiZhangPanel-Free/releases/latest/download/qizhang-panel-free-setup.exe'
    gitlab = 'https://gitlab.com/EeryFrank/QiZhangPanel-Free/-/releases/permalink/latest/downloads/qizhang-panel-free-setup.exe'
}
New-Item -ItemType Directory -Path $verificationDirectory -ErrorAction Stop | Out-Null
foreach ($hostName in $downloadLinks.Keys) {
    $destination = Join-Path $verificationDirectory "$hostName-setup.exe"
    Invoke-WebRequest -Uri $downloadLinks[$hostName] -OutFile $destination -UseBasicParsing -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $expected) {
        throw "$hostName latest download does not match this release."
    }
}
```

任何一项失败，都应保留失败记录并修复缺失的附件或链接；不得通过更改本地预期哈希来迁就错误下载。完成双站标签、版本附件及固定入口校验后，才可宣布本次发布已完成。
