<!-- Source: https://docs.pipecat.ai/api-reference/server/services/s2s/gemini-live -->
<!-- Fetched: 2026-08-13 16:26:54 UTC -->

- 
- 
- 
- 
- 
- 
- 
- Gemini Live - Pipecat
- 
- 
- 
- 
- 
- 
- 
- 
- 
- 
- 
- 

## Documentation Index
Fetch the complete documentation index at: [/llms.txt](/llms.txt)
Use this file to discover all available pages before exploring further.

[Skip to main content](#content-area)
[Pipecat home page](/)

Search...

⌘K

- [Join the Discord](https://discord.gg/pipecat)

- [Github](https://github.com/pipecat-ai/pipecat)

Search...

Navigation
Realtime LLM
Gemini Live

[Overview
](/overview/introduction)[Pipecat
](/pipecat/get-started/introduction)[Pipecat Clients
](/client/introduction)[Pipecat Flows
](/pipecat-flows/introduction)[Pipecat Cloud
](/pipecat-cloud/introduction)[API Reference
](/api-reference)

- [
Pipecat Events](https://pipecat.ai/events)

- [
Community](https://discord.gg/pipecat)

- [
GitHub](https://github.com/pipecat-ai/pipecat)

- [
Changelog](https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md)

### Get Started

- [Overview

](/api-reference)

### Pipecat Server

- [Overview

](/api-reference/server/introduction)

- Services

- [Supported Services

](/api-reference/server/services/supported-services)

- [Community Integrations

](/api-reference/server/services/community-integrations)

- Transport

- Serializers

- Speech-to-Text

- LLM

- Text-to-Speech

- Realtime LLM

- [AWS Nova Sonic

](/api-reference/server/services/s2s/aws)

- [Gemini Live

](/api-reference/server/services/s2s/gemini-live)

- [Gemini Live Vertex AI

](/api-reference/server/services/s2s/gemini-live-vertex)

- [Grok Realtime

](/api-reference/server/services/s2s/grok)

- [Inworld Realtime

](/api-reference/server/services/s2s/inworld)

- [OpenAI Realtime

](/api-reference/server/services/s2s/openai)

- [Ultravox Realtime

](/api-reference/server/services/s2s/ultravox)

- Image Generation

- Video

- Memory

- Vision

- Analytics & Monitoring

- Knowledge Retrieval

- Translation

- Audio Filters

- VAD

- Extensions

- Utilities

- Events

- RTVI

- Frames

- Workers

- Pipeline

- Bus

### Client SDKs

- JavaScript SDK

- React SDK

- React Native SDK

- iOS SDK

- Android SDK

- C++ SDK

### Pipecat Flows

- [Overview

](/api-reference/pipecat-flows/overview)

- [FlowManager

](/api-reference/pipecat-flows/flow-manager)

- [Types

](/api-reference/pipecat-flows/types)

- [Exceptions

](/api-reference/pipecat-flows/exceptions)

### Pipecat Cloud

- REST Reference

- SDK Reference

### CLI

- [CLI Overview

](/api-reference/cli/overview)

- Commands

### Pipecat Context Hub

- [Pipecat Context Hub

](/api-reference/context-hub)

## On this page

- [Overview](#overview)

- [Installation](#installation)

- [Prerequisites](#prerequisites)
- [Google AI Setup](#google-ai-setup)

- [Required Environment Variables](#required-environment-variables)

- [Key Features](#key-features)

- [Configuration](#configuration)
- [GeminiLiveLLMService](#geminilivellmservice)

- [Settings](#settings)

- [GeminiVADParams](#geminivadparams)

- [ContextWindowCompressionParams](#contextwindowcompressionparams)

- [Usage](#usage)
- [Basic Setup](#basic-setup)

- [With Settings](#with-settings)

- [With Local VAD](#with-local-vad)

- [Text-Only Mode](#text-only-mode)

- [With Thinking Enabled](#with-thinking-enabled)

- [Notes](#notes)

[Pipecat Server](/api-reference/server/introduction)
[Services](/api-reference/server/services/supported-services)
[Realtime LLM](/api-reference/server/services/s2s/aws)

# Gemini Live
Copy pageCopy page

GeminiLiveLLMService connects Pipecat to Google’s Gemini Live API for real-time speech-to-speech multimodal conversation.

Copy pageCopy page

## [​
](#overview)
Overview

`GeminiLiveLLMService` enables natural, real-time conversations with Google’s Gemini model. It provides built-in audio transcription, voice activity detection, and context management for creating interactive AI experiences with multimodal capabilities including audio, video, and text processing.

Want to start building? Check out our [Gemini Live
Guide](/pipecat/features/gemini-live).

## Gemini Live API Reference
Pipecat’s API methods for Gemini Live integration

## Example Implementation
Complete Gemini Live async tool calling example

## Gemini Documentation
Official Google Gemini Live API documentation

## Gemini Live Model Card
Gemini Live available models

## [​
](#installation)
Installation

To use Gemini Live services, install the required dependencies:

`uv add "pipecat-ai[google]"
`

## [​
](#prerequisites)
Prerequisites

### [​
](#google-ai-setup)
Google AI Setup

Before using Gemini Live services, you need:

- Google Account: Set up at [Google AI Studio](https://aistudio.google.com/)

- API Key: Generate a Gemini API key from AI Studio

- Model Access: Ensure access to Gemini Live models

- Multimodal Configuration: Set up audio, video, and text modalities

### [​
](#required-environment-variables)
Required Environment Variables

- `GOOGLE_API_KEY`: Your Google Gemini API key for authentication

### [​
](#key-features)
Key Features

- Multimodal Processing: Handle audio, video, and text inputs simultaneously

- Real-time Streaming: Low-latency audio and video processing

- Voice Activity Detection: Automatic speech detection and turn management

- Function Calling: Advanced tool integration and API calling capabilities

- Context Management: Intelligent conversation history and system instruction handling

## [​
](#configuration)
Configuration

### [​
](#geminilivellmservice)
GeminiLiveLLMService

[​
](#param-api-key)
api_keystr
required

Google AI API key for authentication.

[​
](#param-model)
modelstr
deprecated

Gemini model identifier to use.Deprecated in v0.0.105. Use `settings=GeminiLiveLLMService.Settings(model=...)` instead.

[​
](#param-voice-id)
voice_idstr
default:"Charon"
deprecated

TTS voice identifier for audio responses.Deprecated in v0.0.105. Use `settings=GeminiLiveLLMService.Settings(voice=...)` instead.

[​
](#param-system-instruction)
system_instructionstr
default:"None"

System prompt for the model. Can also be provided via the LLM context.

[​
](#param-tools)
toolsToolsSchema | List[FunctionSchema | DirectFunction] | List[dict]
default:"None"

Tools available to the model: a `ToolsSchema`, a plain list of direct
functions and/or `FunctionSchema` objects, or a list of provider-native tool
dicts. Can also be provided via the LLM context.

[​
](#param-params)
paramsInputParams
default:"InputParams()"
deprecated

Runtime-configurable generation and session settings. See
[Settings](#settings) below.Deprecated in v0.0.105. Use `settings=GeminiLiveLLMService.Settings(...)` instead.

[​
](#param-settings)
settingsGeminiLiveLLMService.Settings
default:"None"

Runtime-configurable settings. See [Settings](#settings) below.

[​
](#param-start-audio-paused)
start_audio_pausedbool
default:"False"

Whether to start with audio input paused.

[​
](#param-start-video-paused)
start_video_pausedbool
default:"False"

Whether to start with video input paused.

[​
](#param-inference-on-context-initialization)
inference_on_context_initializationbool
default:"True"

Whether to generate a response when context is first set. Set to `False` to
wait for user input before the model responds.

[​
](#param-http-options)
http_optionsHttpOptions
default:"None"

HTTP options for the Google API client. Use this to set API version (e.g.
`HttpOptions(api_version="v1alpha")`) or other request options.

[​
](#param-file-api-base-url)
file_api_base_urlstr

Base URL for the Gemini File API.

### [​
](#settings)
Settings

Runtime-configurable settings passed via the `settings` constructor argument using `GeminiLiveLLMService.Settings(...)`. These can be updated mid-conversation with `LLMUpdateSettingsFrame`. See [Service Settings](/pipecat/fundamentals/service-settings) for details.
ParameterTypeDefaultDescription
`model``str``NOT_GIVEN`Model identifier. (Inherited from base settings.)
`system_instruction``str``NOT_GIVEN`System instruction/prompt. (Inherited from base settings.)
`temperature``float``NOT_GIVEN`Sampling temperature (0.0-2.0). (Inherited from base settings.)
`max_tokens``int``NOT_GIVEN`Maximum tokens to generate. (Inherited from base settings.)
`top_k``int``NOT_GIVEN`Top-k sampling parameter. (Inherited from base settings.)
`top_p``float``NOT_GIVEN`Top-p (nucleus) sampling parameter (0.0-1.0). (Inherited from base settings.)
`frequency_penalty``float``NOT_GIVEN`Frequency penalty for generation (0.0-2.0). (Inherited from base settings.)
`presence_penalty``float``NOT_GIVEN`Presence penalty for generation (0.0-2.0). (Inherited from base settings.)
`voice``str``NOT_GIVEN`TTS voice identifier (e.g. `"Charon"`, `"Puck"`).
`modalities``GeminiModalities``NOT_GIVEN`Response modality: `GeminiModalities.AUDIO` or `GeminiModalities.TEXT`. Note: TEXT modality may not be supported by recent models.
`language``Language | str``NOT_GIVEN`Language for generation and transcription.
`media_resolution``GeminiMediaResolution``NOT_GIVEN`Media resolution for video input: `UNSPECIFIED`, `LOW`, `MEDIUM`, or `HIGH`.
`vad``GeminiVADParams``NOT_GIVEN`Voice activity detection parameters. See [GeminiVADParams](#geminivadparams) below.
`context_window_compression``ContextWindowCompressionParams | dict``NOT_GIVEN`Context window compression settings.
`thinking``ThinkingConfig | dict``NOT_GIVEN`Thinking/reasoning configuration. Requires a model that supports it.
`enable_affective_dialog``bool``NOT_GIVEN`Enable affective dialog for expression and tone adaptation.
`proactivity``ProactivityConfig | dict``NOT_GIVEN`Proactivity settings for model behavior.

`NOT_GIVEN` values are omitted, letting the service use its own defaults (e.g.
`"models/gemini-2.5-flash-native-audio-preview-12-2025"` for model, `"Charon"`
for voice, `4096` for max_tokens). Only parameters that are explicitly set are
included.

### [​
](#geminivadparams)
GeminiVADParams

Voice activity detection configuration passed via the `vad` Settings field:
ParameterTypeDefaultDescription
`disabled``bool``None`Whether to disable server-side VAD. `None`/`False` enables server-side VAD (default), `True` enables local VAD.
`start_sensitivity``StartSensitivity``None`Sensitivity for speech start detection.
`end_sensitivity``EndSensitivity``None`Sensitivity for speech end detection.
`prefix_padding_ms``int``None`Padding before speech starts in milliseconds.
`silence_duration_ms``int``None`Silence duration threshold in milliseconds to detect speech end.

### [​
](#contextwindowcompressionparams)
ContextWindowCompressionParams

ParameterTypeDefaultDescription
`enabled``bool``False`Whether context window compression is enabled.
`trigger_tokens``int``None`Token count to trigger compression. `None` uses the default (80% of context window).

## [​
](#usage)
Usage

### [​
](#basic-setup)
Basic Setup

`import os
from pipecat.services.google.gemini_live import GeminiLiveLLMService

llm = GeminiLiveLLMService(
api_key=os.getenv("GOOGLE_API_KEY"),
settings=GeminiLiveLLMService.Settings(
voice="Charon",
system_instruction="You are a helpful assistant.",
),
)
`

### [​
](#with-settings)
With Settings

`from pipecat.services.google.gemini_live import (
GeminiLiveLLMService,
GeminiVADParams,
ContextWindowCompressionParams,
)

llm = GeminiLiveLLMService(
api_key=os.getenv("GOOGLE_API_KEY"),
settings=GeminiLiveLLMService.Settings(
model="models/gemini-2.5-flash-native-audio-preview-12-2025",
system_instruction="You are a helpful assistant.",
voice="Puck",
temperature=0.7,
max_tokens=2048,
language="en-US",
vad=GeminiVADParams(
silence_duration_ms=500,
),
context_window_compression={"enabled": True},
),
)
`

### [​
](#with-local-vad)
With Local VAD

`from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.google.gemini_live import (
GeminiLiveLLMService,
GeminiVADParams,
)
from pipecat.processors.aggregators.llm_response_universal import (
LLMContextAggregatorPair,
LLMUserAggregatorParams,
)

llm = GeminiLiveLLMService(
api_key=os.getenv("GOOGLE_API_KEY"),
settings=GeminiLiveLLMService.Settings(
voice="Charon",
vad=GeminiVADParams(disabled=True), # Disable server-side VAD
),
)

# Configure local VAD in your aggregator. realtime_service_mode=True keeps
# context-writing correct with a realtime service; the local VAD here drives
# turn-taking since server-side VAD is disabled.
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
context,
realtime_service_mode=True,
user_params=LLMUserAggregatorParams(
vad_analyzer=SileroVADAnalyzer(),
),
)
`

Pass `realtime_service_mode=True` to `LLMContextAggregatorPair` for any
realtime (speech-to-speech) service. See [Realtime (Speech-to-Speech)
Services](/api-reference/server/utilities/turn-management/external-turn-management#realtime-speech-to-speech-services)
for what it does and how it interacts with local VAD.

### [​
](#text-only-mode)
Text-Only Mode

TEXT modality may not be supported by recent Gemini Live models. The service
will log a warning if you configure `modalities=GeminiModalities.TEXT`.

`from pipecat.services.google.gemini_live import (
GeminiLiveLLMService,
GeminiModalities,
)

llm = GeminiLiveLLMService(
api_key=os.getenv("GOOGLE_API_KEY"),
settings=GeminiLiveLLMService.Settings(
system_instruction="You are a helpful assistant.",
modalities=GeminiModalities.TEXT,
),
)
`

### [​
](#with-thinking-enabled)
With Thinking Enabled

`from google.genai.types import ThinkingConfig

llm = GeminiLiveLLMService(
api_key=os.getenv("GOOGLE_API_KEY"),
settings=GeminiLiveLLMService.Settings(
model="models/gemini-2.5-flash-native-audio-preview-12-2025",
system_instruction="You are a helpful assistant.",
thinking=ThinkingConfig(include_thoughts=True),
),
)
`

The `InputParams` / `params=` pattern is deprecated as of v0.0.105. Use
`Settings` / `settings=` instead. See the [Service Settings
guide](/pipecat/fundamentals/service-settings) for migration details.

## [​
](#notes)
Notes

- Model support: The service supports both Gemini 2.5 and Gemini 3.x models. The service automatically detects and handles model-specific behavior.

- Async tool support: Functions registered with `cancel_on_interruption=False` use Gemini’s NON_BLOCKING tool mechanism on models that support it (currently Gemini 2.x), allowing the conversation to continue while the tool runs in the background. The result is delivered via the async-tool mechanism and integrated into the model’s next turn. On models that don’t support NON_BLOCKING (Gemini 3.x), the service logs a one-time warning explaining the limitation. Note: An intermittent 1008 error can occasionally occur on Gemini 2.5 during long-running tool calls; the service auto-reconnects when this happens.

- Tool calls in conversation history: When seeding a session with conversation history that contains tool calls (e.g., after a multi-worker handoff or reconnect), the service automatically converts function calls and their results to text summaries. This is required because Gemini Live’s API only accepts text and media content. The conversion happens transparently and preserves the context for the model.

- System instruction precedence: The `system_instruction` from service settings takes precedence over an initial system message in the LLM context. A warning is logged when both are set.

- VAD modes: By default, Gemini Live uses server-side VAD for detecting when the user starts and stops speaking. To use local VAD (e.g., Silero), set `vad=GeminiVADParams(disabled=True)` and configure an external VAD analyzer in your `LLMUserAggregatorParams`. The service will automatically send activity signals to the Gemini API when local VAD detects speech.

- Tools precedence: Similarly, tools provided in the context override tools provided at init time.

- Transcription aggregation: Gemini Live sends user transcriptions in small chunks. The service aggregates them into complete sentences using end-of-sentence detection with a 0.5-second timeout fallback.

- Session resumption: The service automatically handles session resumption on reconnection using session resumption handles. In the rare case where reconnection occurs before a resumption handle is received, conversation history is preserved by reseeding it into the new session.

- Connection resilience: The service will attempt up to 3 consecutive reconnections before treating a connection failure as fatal.

- Video frame rate: Video frames are throttled to a maximum of one per second.

- Affective dialog and proactivity: These features require both a supporting model and API version (`v1alpha`).

[AWS Nova Sonic
](/api-reference/server/services/s2s/aws)[Gemini Live Vertex AI
](/api-reference/server/services/s2s/gemini-live-vertex)
⌘I

[x](https://x.com/pipecat_ai)[github](https://github.com/pipecat-ai/pipecat)[discord](https://discord.gg/pipecat)
[Powered byThis documentation is built and hosted on Mintlify, a developer documentation platform](https://www.mintlify.com?utm_campaign=poweredBy&utm_medium=referral&utm_source=daily)