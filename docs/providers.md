# ASR providers and ecosystem notes

Voice Input Bridge keeps the provider boundary narrow: a provider receives a PCM stream and yields `TranscriptEvent` objects. Transport, authentication, session limits, and text injection are handled by the core.

## Built-in providers

| Name | Real-time | Final scope | Optional dependency | Credential |
| --- | --- | --- | --- | --- |
| `mock` | partial + final | one deterministic final | none | none |
| `aliyun` | partial + final | one or more sentence finals | `dashscope` | `DASHSCOPE_API_KEY` |
| `deepgram` | partial + final | result segments | none beyond `websockets` | `DEEPGRAM_API_KEY` |
| `command` | final only | one final after the audio ends | none | command-defined |

## Vendor integration matrix

Separate **"the vendor offers streaming"** from **"this project already ships an adapter"**. Only `aliyun`, `deepgram`, `mock`, and `command` are built-in providers. Other vendors require a provider plugin or a `command` wrapper; changing one `provider = "vendor"` value is not enough.

| Region | Vendor / service | Integration in this project | Official streaming note | Official entry |
| --- | --- | --- | --- | --- |
| China | Alibaba Cloud Paraformer Realtime V2 | **Built-in `aliyun`** | partial + final; Chinese real-time dictation | [Docs](https://help.aliyun.com/zh/model-studio/paraformer-real-time-speech-recognition-api) · [Console](https://bailian.console.aliyun.com/) · [Pricing](https://help.aliyun.com/zh/model-studio/model-pricing) |
| China | Tencent Cloud real-time ASR | Plugin / custom adapter required | Official streaming API; not built in here | [Docs](https://cloud.tencent.com/document/product/1093) · [Console](https://console.cloud.tencent.com/asr) · [Pricing](https://cloud.tencent.com/document/product/1093/35686) |
| China | iFlytek real-time transcription | Plugin / custom adapter required | Official real-time WebSocket API | [Docs](https://www.xfyun.cn/doc/asr/rtasr/API.html) · [Console](https://console.xfyun.cn/) |
| China | Baidu Cloud speech recognition | Plugin / custom adapter required | Implement Baidu authentication and audio streaming | [Docs](https://cloud.baidu.com/doc/SPEECH/s/2k5dllqxj) · [Product/pricing](https://cloud.baidu.com/product/speech/asr) |
| China | Volcano Engine streaming ASR | Plugin / custom adapter required | Confirm model, region, and authentication in official docs | [Docs](https://www.volcengine.com/docs/6561/1354869) · [Product/pricing](https://www.volcengine.com/product/asr) |
| China | Huawei Cloud SIS real-time ASR | Plugin / custom adapter required | Official Real-Time ASR request API | [Docs](https://support.huaweicloud.com/intl/en-us/api-sis/sis_03_0029.html) · [Product/pricing](https://www.huaweicloud.com/product/sis.html) |
| Global | Deepgram | **Built-in `deepgram`** | partial + final; WebSocket linear16 | [Docs](https://developers.deepgram.com/docs/live-streaming-audio) · [Pricing](https://deepgram.com/pricing) |
| Global | Microsoft Azure AI Speech | Plugin / custom adapter required | Speech SDK / streaming API | [Docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-to-text) · [Pricing](https://azure.microsoft.com/en-us/pricing/details/speech/) |
| Global | Google Cloud Speech-to-Text | Plugin / custom adapter required | Streaming Recognize API | [Docs](https://cloud.google.com/speech-to-text/docs/streaming-recognize) · [Pricing](https://cloud.google.com/speech-to-text/pricing) |
| Global | Amazon Transcribe Streaming | Plugin / custom adapter required | Official streaming API with AWS auth | [Docs](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html) · [Pricing](https://aws.amazon.com/transcribe/pricing/) |
| Global | AssemblyAI | Plugin / custom adapter required | Universal Streaming WebSocket | [Docs](https://www.assemblyai.com/docs/streaming/getting-started/transcribe-streaming-audio) · [Pricing](https://www.assemblyai.com/pricing) |
| Global | Speechmatics | Plugin / custom adapter required | Realtime API; use the official WebSocket contract | [Docs](https://docs.speechmatics.com/speech-to-text/realtime/quickstart) · [Pricing](https://www.speechmatics.com/pricing) |
| Global | Soniox | Plugin / custom adapter required | Real-time transcription API | [Docs](https://docs.soniox.com/stt/rt/real-time-transcription) · [Pricing](https://soniox.com/pricing/) |
| Global | OpenAI Speech to Text | Plugin / custom adapter required | Check current streaming/model support in the official docs; not built in here | [Docs](https://platform.openai.com/docs/guides/speech-to-text) · [Pricing](https://openai.com/api/pricing/) |
| Local | whisper.cpp | **Built-in `command` / final-only** | Usually returns after a complete recording; real-time needs a plugin or server mode | [GitHub](https://github.com/ggml-org/whisper.cpp) |
| Local | faster-whisper | **Built-in `command` / final-only** | Usually file or chunk inference; add chunking for streaming | [GitHub](https://github.com/SYSTRAN/faster-whisper) |
| Local | FunASR | **Built-in `command` / final-only** | Use its streaming API inside a custom provider for partials | [GitHub](https://github.com/modelscope/FunASR) |
| Local | Vosk | **Built-in `command` / final-only** | Offline; manage model, memory, and chunking yourself | [GitHub](https://github.com/alphacep/vosk-api) |
| Local | sherpa-onnx | Plugin / custom adapter required | Local inference on multiple platforms; implement a provider for each model/runtime | [GitHub](https://github.com/k2-fsa/sherpa-onnx) |
| Test | mock | **Built-in `mock`** | Deterministic partial + final; no network | [Local docs](providers.md) |

### Alibaba Cloud Paraformer Realtime V2

```toml
[asr]
provider = "aliyun"

[asr.aliyun]
model = "paraformer-realtime-v2"
api_key = "${DASHSCOPE_API_KEY}"
workspace_id = "${DASHSCOPE_WORKSPACE_ID}"
region = "${DASHSCOPE_REGION:-}"
vocabulary_id = "${DASHSCOPE_VOCABULARY_ID:-}"
language_hints = ["zh", "en"]
final_timeout_seconds = 20
```

- Install: `pip install "voice-input-bridge[aliyun]"`
- Audio: mono 16-bit PCM at 8 kHz or 16 kHz.
- Strength: Chinese real-time results, punctuation, language hints, and a documented vocabulary ID path.
- Risks: cloud latency and availability, workspace/region configuration drift, provider SDK changes, and usage charges.
- Console: <https://bailian.console.aliyun.com/>
- Official docs: <https://help.aliyun.com/zh/model-studio/paraformer-real-time-speech-recognition-api>
- Billing: <https://help.aliyun.com/zh/model-studio/billing-for-model-studio>

The provider uses the official DashScope Python SDK. Its public GitHub repository has a relatively small star count because the SDK is distributed primarily through the vendor console/PyPI, not because it is an unmaintained hobby project. The adoption evidence is the vendor ownership, current PyPI release, package downloads, and official API documentation.

### Deepgram

```toml
[asr]
provider = "deepgram"

[asr.deepgram]
endpoint = "wss://api.deepgram.com/v1/listen"
api_key = "${DEEPGRAM_API_KEY}"
model = "nova-3"
language = "zh-CN"
smart_format = true
punctuate = true
interim_results = true
final_timeout_seconds = 20
```

- Install: no provider extra; the adapter uses the existing `websockets` dependency.
- Audio: linear16 PCM; channel count is passed through to Deepgram.
- Strength: direct WebSocket integration, multilingual service, partial and is_final results, and a clean cloud API.
- Risks: cloud latency and availability, language/model differences, billing, and result semantics that can change by model.
- Docs: <https://developers.deepgram.com/docs/live-streaming-audio>
- Pricing: <https://deepgram.com/pricing>

The adapter talks to the documented WebSocket endpoint directly, so it does not depend on the larger Deepgram SDK. The SDK is still relevant ecosystem evidence: it has frequent releases and substantial PyPI usage.

### local and command-line ASR

`command` is the generic bridge for tools that accept a WAV path and print recognized text:

```toml
[asr]
provider = "command"

[asr.command]
command = [
  "whisper-cli",
  "-m", "models/ggml-base.bin",
  "-f", "{wav}",
  "-l", "{language_short}",
  "-nt",
]
timeout_seconds = 180
max_audio_seconds = 120
output_encoding = "utf-8"
```

Placeholders:

- `{wav}` — temporary mono/stereo PCM WAV path.
- `{language}` — full language, for example `zh-CN`.
- `{language_short}` — primary language, for example `zh`.
- `{sample_rate}` — the declared sample rate.

The bridge invokes the command without a shell. This avoids shell interpolation, but it also means pipes and redirection must be implemented by a wrapper script. The temporary WAV is deleted after the command exits.

Local adapters are final-only by design: almost every command-line ASR tool needs a complete file. The user therefore hears no text until `stop`. A true streaming local provider should be implemented as a plugin that consumes `request.audio` incrementally.

#### whisper.cpp

- Strong choice for offline, CPU-capable dictation and edge machines.
- 20 ms streaming is possible only through a plugin/server mode; the included command adapter is final-only.
- Model size and speed depend heavily on quantization and CPU.
- Docs: <https://github.com/ggml-org/whisper.cpp>

#### faster-whisper

- Mature Python implementation backed by CTranslate2.
- Faster than reference Whisper on many CPUs/GPUs, but still usually buffers or chunks audio and uses substantial memory for larger models.
- A plugin can stream with `vad_filter`/chunking, but this is not implemented in the core command adapter.
- Docs: <https://github.com/SYSTRAN/faster-whisper>

#### FunASR

- Strong Chinese/offline model ecosystem and streaming interfaces.
- Its package surface and model/runtime dependencies are larger than a simple cloud WebSocket adapter.
- A production integration should pin model revisions and test memory/latency on the target machine.
- Docs: <https://github.com/modelscope/FunASR>

#### Vosk

- Small offline models and a long-standing API.
- Treat the project as lower-momentum than the others: the latest Python package release in the checked snapshot is old and the repository has many open issues.
- Validate current model/license support for Chinese before deployment.
- Docs: <https://github.com/alphacep/vosk-api>

### Adding a third-party provider

Create a package that depends on `voice-input-bridge`, subclass `ASRProvider`, and register it:

```toml
[project.entry-points."voicebridge.providers"]
my_asr = "my_package.provider:MyASRProvider"
```

```python
from collections.abc import AsyncIterator

from voicebridge.providers.base import ASRProvider, ProviderRequest
from voicebridge.models import TranscriptEvent


class MyASRProvider(ASRProvider):
    name = "my_asr"

    async def stream(self, request: ProviderRequest) -> AsyncIterator[TranscriptEvent]:
        async for pcm in request.audio:
            ...
        yield TranscriptEvent(text="final text", final=True, provider=self.name)
```

The plugin must document whether partial text is cumulative, whether finals are segment-level, whether credentials are required, and whether audio leaves the machine. Providers should raise `ProviderUnavailable` for missing credentials/dependencies and `ProviderError` for upstream failures.

## Adoption and risk snapshot

Collected on **2026-11-18** from PyPI metadata, pypistats, GitHub API, and OSV. Download counts are package downloads, not unique users. Star counts are not quality proof.

| Package/project | Latest release checked | GitHub stars | PyPI downloads, last 30 days | License | Notes |
| --- | ---: | ---: | ---: | --- | --- |
| `websockets` | 17.4 (2026-10-30) | 5,746 | 539,059,644 | BSD-3-Clause | Active; the project pins `<16` for Python 3.10/API compatibility |
| `pyserial` | 3.5 (2020-11-23) | 3,602 | 16,995,859 | BSD-style | Stable but low release cadence; isolated optional dependency |
| `dashscope` | 2.1.0 (2026-11-13) | 81 (official SDK repo) | 1,964,161 | Apache-2.0 | Vendor-owned; small star count is not the primary adoption signal |
| `deepgram-sdk` | 7.19.0 (2026-11-13) | 479 | 3,991,031 | MIT | Active vendor SDK; not required by this adapter |
| `faster-whisper` | 1.2.1 (2025-10-31) | 26,845 | 19,829,714 | MIT | Active local inference ecosystem; memory/CPU heavy |
| `funasr` | 1.4.27 (2026-11-17) | 21,063 | 456,158 | MIT | Active Chinese ASR ecosystem; larger dependency surface |
| `whisper.cpp` | repository active 2026-11-18 | 55,283 | n/a | MIT | Very mature C/C++ local inference project |
| `vosk` | 0.3.45 (2022-12-14) | 15,273 | n/a | Apache-2.0 | Long-standing but slower release pace and many open issues |

OSV exact-version queries for `websockets@15.0.1`, `pyserial@3.5`, `dashscope@2.1.0`, `deepgram-sdk@7.19.0`, `faster-whisper@1.2.1`, `funasr@1.4.27`, and `vosk@0.3.45` returned no known advisories at the snapshot time. This is not a guarantee; re-run dependency and vulnerability checks before every release.

## Selection guidance

- **Chinese cloud dictation, lowest integration effort:** Aliyun Paraformer Realtime V2.
- **Global/multilingual cloud dictation:** Deepgram.
- **Offline and memory is not a constraint:** whisper.cpp or faster-whisper through a streaming plugin.
- **Offline and memory is tight:** a small Vosk/whisper.cpp model or a custom streaming plugin; do not assume a large Whisper model will fit.
- **Protocol/CI:** `mock`.
- **Vendor CLI already installed:** `command`, accepting final-only latency.

Provider pricing and quotas are intentionally not copied here because they change frequently. Confirm the effective region, model, free tier, concurrency limit, and audio-duration billing in the provider console before deployment.
