"""意见池（M11 第一阶段，设计 `doc/design/M11-分块-第一阶段最小闭环.md`）。

读者（网站改字、一段有问题、精校票、通用反馈）与以后的机器意见，统一规整成 ``guji-opinion/0.1``，
存进中心库的文件 ``feedback/lists/opinions/<书>/``；再配证据、按规则分流、交用户裁决，
采纳的经修订工具改 book-text 冻结册出 1.x 新版本。

只依赖标准库、Pillow、``core``（路径）与 ``datastore``（中心库客户端），不碰任何 Step，
不进任何 Step 的 ``code_deps``，各书产物指纹不变。

模块：``schema``（数据形）、``store``（五个文件的读写，本地或经 Worker ``/v1/files``）、
``ingest``（三源入池）、``textsrc``（book-text 的 char/cord/CHANGES）、``evidence``（证据包）、
``rules``（确定性分流）、``revise``（A／B／B′ 类修订）。命令行在 ``cli_opinions``（``guji opinions …``）。
"""
