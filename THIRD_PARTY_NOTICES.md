# Third-party notices

Voice Input Bridge is an independent project. It does not vendor or relicense third-party source code in this repository unless a file explicitly says otherwise.

## Runtime dependencies

The following packages are installed separately by the user or package manager. Their own licenses apply.

| Package | Purpose | Declared license | Project |
| --- | --- | --- | --- |
| `websockets` | WebSocket transport | BSD-3-Clause | <https://github.com/python-websockets/websockets> |
| `tomli` | TOML parsing on Python 3.10 | MIT | <https://github.com/hukkin/tomli> |
| `pyserial` | Optional USB serial transport | BSD-3-Clause | <https://github.com/pyserial/pyserial> |
| `dashscope` | Optional Alibaba Cloud Paraformer adapter | Apache-2.0 | <https://pypi.org/project/dashscope/> |
| `pyobjc-framework-Quartz` | Optional macOS text injection | MIT | <https://github.com/ronaldoussoren/pyobjc> |

Development-only tools such as `pytest`, `pytest-asyncio`, `ruff`, `build`, `twine`, `setuptools`, and `wheel` are not part of the project's runtime bundle. Their licenses are available from their respective distributions.

## Cloud and platform services

The project can interoperate with services and platforms including Alibaba Cloud, Tencent Cloud, iFlytek, Baidu Cloud, Volcano Engine, Huawei Cloud, Deepgram, Microsoft Azure, Google Cloud, Amazon Web Services, AssemblyAI, Speechmatics, Soniox, OpenAI, Microsoft Windows, Apple macOS, Espressif, Arduino, and M5Stack.

These names and trademarks belong to their respective owners. Their inclusion does not imply affiliation, sponsorship, authorization, certification, or endorsement. Service availability, pricing, model names, event formats, and data-processing terms are controlled by those third parties and may change.

## Model files and examples

No third-party model weights are included in this repository. Users must obtain model files and device libraries from their official sources and comply with the applicable licenses. Example firmware may reference libraries that are installed separately through the Arduino or M5Stack toolchain.

When redistributing a build, verify the licenses of every dependency, model, firmware library, and asset included in that build. This notice is not a substitute for a dependency license audit.
