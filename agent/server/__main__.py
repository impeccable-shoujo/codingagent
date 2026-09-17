"""python -m agent.server 的入口。

必须用 -m 方式启动：相对导入需要包上下文。直接执行本文件
（python agent/server/__main__.py）会因为缺少父包而失败，
下面把那种失败换成一句明确的指引。

另外，服务要在仓库根目录启动：.env 与相对路径是按当前工作目录解析的，
在别的目录启动会读不到配置。
"""

import sys

# 直接执行脚本时 __package__ 为空字符串，这是与 -m 启动最可靠的区分方式。
# 不能靠捕获 ImportError 来判断——那会把 main.py 内部真实的导入错误
# （比如没装 fastapi）也误报成"启动方式不对"。
if not __package__:
    print(
        "这个文件不能直接运行，相对导入需要包上下文。\n"
        "请回到仓库根目录，用模块方式启动：\n"
        "\n"
        "    cd <仓库根目录>\n"
        "    python -m agent.server\n"
        "\n"
        "注意必须在该目录执行，否则读不到 .env，会报「未提供 API Key」。\n"
        "也可以直接双击 scripts/start-all.bat 一键启动前后端。",
        file=sys.stderr,
    )
    raise SystemExit(2)

from .main import main  # noqa: E402

raise SystemExit(main())
