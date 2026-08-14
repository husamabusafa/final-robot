<!-- Fetched: 2026-08-13 18:51:31 UTC -->

##### Copyright 2026 Google LLC.



python
#@title Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.




# Multimodal Live API - Quickstart

<a target="_blank" href="https://colab.research.google.com/github/google-gemini/cookbook/blob/main/quickstarts/Get_started_LiveAPI.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" height=30/></a>

**Preview**: The Live API is in preview.

This notebook demonstrates simple usage of the Gemini Live API. For an overview of new capabilities refer to the [Gemini Live API docs](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

This notebook implements a simple turn-based chat where you send messages as text, and the model replies with audio. The API is capable of much more than that. The goal here is to demonstrate with **simple code**.

Some features of the API are not working in Colab, to try them it is recommended to have a look at the Live API examples in [GitHub](https://github.com/google-gemini/gemini-live-api-examples).

If you aren't looking for code, and just want to try multimedia streaming use [Live API in Google AI Studio](https://aistudio.google.com/live).

The [Next steps](#next_steps) section at the end of this tutorial provides links to additional resources.

## Setup

### Install SDK

The new **[Google Gen AI SDK](https://ai.google.dev/gemini-api/docs/sdks)** provides programmatic access to Gemini 3 (and previous models) using both the [Google AI for Developers](https://ai.google.dev/gemini-api/docs) and [Vertex AI](https://cloud.google.com/vertex-ai/generative-ai/docs/overview) APIs. With a few exceptions, code that runs on one platform will run on both.

More details about this new SDK on the [documentation](https://ai.google.dev/gemini-api/docs/sdks) or in the [Getting started](../quickstarts/Get_started.ipynb) notebook.



python
%pip install -U -q google-genai




### Set up your API key

To run the following cell, your API key must be stored in a Colab Secret named `GEMINI_API_KEY`. If you don't already have an API key, or you're not sure how to create a Colab Secret, see [Authentication ![image](https://storage.googleapis.com/generativeai-downloads/images/colab_icon16.png)](../quickstarts/Authentication.ipynb) for an example.



python
from google.colab import userdata
import os

os.environ['GEMINI_API_KEY'] = userdata.get('GEMINI_API_KEY')




### Initialize SDK client

The client will pick up your API key from the environment variable.



python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])




### Select a model

The [Gemini 3.1 Flash Live](https://ai.google.dev/gemini-api/docs/models#live-api) model works with the Live API to enable low-latency bidirectional voice and video interactions with Gemini. The model can process text, audio, and video frames (images) input, and it can provide audio output (with optional transcriptions).



python
MODEL = 'gemini-3.1-flash-live-preview'  # @param ['gemini-3.1-flash-live-preview'] {allow-input: true, isTemplate: true}




### Import

Import all the necessary modules.



python
import asyncio
import base64
import contextlib
import os
import wave

from IPython.display import display, Audio

from google import genai
from google.genai import types




## Simple text to audio

The simplest way to playback the audio in Colab, is to write it out to a `.wav` file. So here is a simple wave file writer:



python
@contextlib.contextmanager
def wave_file(filename, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        yield wf




Tell the model to return audio by setting `response_modalities=["AUDIO"]` in the `LiveConnectConfig`, and send input text using `send_realtime_input`. When you get a response from the model, write the data to a `.wav` file.

> **Note**: The `TEXT` response modality is no longer supported. Use `AUDIO` with output transcription enabled if you need text alongside audio.



python
config = types.LiveConnectConfig(
    response_modalities=["AUDIO"]
)

async with client.aio.live.connect(model=MODEL, config=config) as session:
    file_name = 'audio.wav'
    with wave_file(file_name) as wav:
        message = "Hello? Gemini are you there?"
        print("> ", message, "\n")
        await session.send_realtime_input(text=message)

        async for response in session.receive():
            if response.data is not None:
                wav.writeframes(response.data)
                print('.', end='')
            if response.server_content and response.server_content.turn_complete:
                break

display(Audio(file_name, autoplay=True))




## Towards Async Tasks

The real power of the Live API is that it's real time, and interruptable. You can't get that full power in a simple sequence of steps. To really use the functionality you will move the `send` and `receive` operations (and others) into their own [async tasks](https://docs.python.org/3/library/asyncio-task.html).

Because of the limitations of Colab this tutorial doesn't totally implement the interactive async tasks, but it does implement the next step in that direction:

- It separates the `send` and `receive`, but still runs them sequentially.  
- In a more complete implementation you'd run these in separate `async` tasks.

Setup a quick logger to make debugging easier (switch to `setLevel('DEBUG')` to see debugging messages).



python
import logging

logger = logging.getLogger('Live')
logger.setLevel('INFO')




The class below implements the interaction with the Live API.



python
async def async_enumerate(aiterable):
    n = 0
    async for item in aiterable:
        yield n, item
        n += 1


class AudioLoop:
    def __init__(self, turns=None, config=None):
        self.session = None
        self.index = 0
        self.turns = turns
        if config is None:
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"]
            )
        self.config = config

    async def run(self):
        logger.debug('connect')
        async with client.aio.live.connect(model=MODEL, config=self.config) as session:
            self.session = session

            async for sent in self.send():
                # Ideally send and recv would be separate tasks.
                await self.recv()

    async def _iter(self):
        for text in self.turns:
            print("message >", text)
            yield text

    async def send(self):
        async for text in self._iter():
            logger.debug('send')

            # Send the message to the model using send_realtime_input.
            await self.session.send_realtime_input(text=text)
            logger.debug('sent')
            yield text

    async def recv(self):
        # Start a new `.wav` file.
        file_name = f"audio_{self.index}.wav"
        with wave_file(file_name) as wav:
            self.index += 1

            logger.debug('receive')

            # Read chunks from the socket.
            async for n, response in async_enumerate(self.session.receive()):
                logger.debug(f'got chunk: {str(response)}')

                if response.data is not None:
                    wav.writeframes(response.data)
                    print('.', end='')
                if response.server_content and response.server_content.turn_complete:
                    break

            print('\n<Turn complete>')

        display(Audio(file_name, autoplay=True))
        await asyncio.sleep(2)




There are 3 methods worth describing here:

**`run` - The main loop**

This method:

- Opens a `websocket` connecting to the Live API.
- Then enters the main loop where it alternates between `send` and `recv` until there are no more turns.
- A production implementation would run `send` and `recv` as separate concurrent `async` tasks.

**`send` - Sends input text to the API**

The `send` method iterates over the hardcoded turns, sends each message to the model via `send_realtime_input`, and yields control back to the run loop so `recv` can collect the response.

**`recv` - Collects audio from the API and plays it**

The `recv` method collects audio chunks in a loop and writes them to a `.wav` file. It breaks out of the loop once the model sends a `turn_complete` signal, and then plays the audio.

To keep things simple in Colab it collects **all** the audio before playing it. [Other examples](#next_steps) demonstrate how to play audio as soon as you start to receive it (using `PyAudio`), and how to interrupt the model (implement input and audio playback on separate tasks).

### Run

Run it:



python
await AudioLoop(['Hello', "What's your name?"]).run()




## Working with resumable sessions

Session resumption allows you to return to a previous interaction with the Live API by sending the last session handle you got from the previous session.

When you set your session to be resumable, the session information keeps stored on the Live API for up to 24 hours. In this time window, you can resume the conversation and refer to previous information you have shared with the model.

The session below uses `AUDIO` output with output transcription enabled so you can read the model responses in the notebook output.

### Helper function

`async_main` runs a list of hardcoded turns in sequence. After each turn it writes the audio response to a `.wav` file, renders it inline, and captures the latest session handle from `session_resumption_update` messages.



python
import asyncio


async def async_main(turns, last_handle=None):
    print(f"Connecting with handle: {last_handle}")
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(
            handle=last_handle,
        )
    )

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        for i, message in enumerate(turns):
            print(f"\n> {message}")
            await session.send_realtime_input(text=message)

            file_name = f"resumable_{i}.wav"
            with wave_file(file_name) as wav:
                async for response in session.receive():
                    if response.data is not None:
                        wav.writeframes(response.data)
                        print('.', end='')
                    # session_resumption_update is a top-level field on the response,
                    # not nested under server_content.
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        if update.resumable and update.new_handle:
                            last_handle = update.new_handle
                    if response.server_content:
                        if response.server_content.output_transcription:
                            print(response.server_content.output_transcription.text, end="")
                        if response.server_content.turn_complete:
                            break

            display(Audio(file_name, autoplay=True))
            await asyncio.sleep(2)

    return last_handle




Run the first session with two questions. The session handle is returned so you can resume later:



python
turns_session_1 = ["Hello, what's your name?", "What is the capital of Brazil?"]
last_handle = await async_main(turns_session_1)




The session handle for resumption is saved in `last_handle`:



python
last_handle




Now start a new Live API session pointing to the previous handle. The model can recall information from the earlier conversation:



python
turns_session_2 = ["What was the second question I asked you in our previous conversation?"]
await async_main(turns_session_2, last_handle)




## Next steps

<a name="next_steps"></a>

This tutorial just shows basic usage of the Live API, using the Python GenAI SDK.

- If you aren't looking for code, and just want to try multimedia streaming use [Live API in Google AI Studio](https://aistudio.google.com/live).
- If you want to see how to setup streaming interruptible audio and video using the Live API see the Live API examples in [GitHub](https://github.com/google-gemini/gemini-live-api-examples).
- If you're interested in the low level details of using the websockets directly, see the [websocket version of this tutorial](../quickstarts/websockets/Get_started_LiveAPI.ipynb).
- Other Gemini examples can also be found in the [Cookbook's example directory](https://github.com/google-gemini/cookbook/tree/main/examples/), in particular the [video understanding](../quickstarts/Video_understanding.ipynb) and the [spatial understanding](../quickstarts/Spatial_understanding.ipynb) ones.

