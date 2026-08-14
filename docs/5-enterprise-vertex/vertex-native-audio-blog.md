<!-- Source: https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai -->
<!-- Fetched: 2026-08-13 16:26:50 UTC -->

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
- 
- How to use Gemini Live API Native Audio in Vertex AI | Google Cloud Blog
- [Jump to Content](./#content)[
Cloud](https://cloud.google.com/)

[Blog](https://cloud.google.com/blog/)

[Contact sales ](https://cloud.google.com/contact/)[Get started for free ](https://console.cloud.google.com/freetrial/)

[
Cloud](https://cloud.google.com/)

[Blog](https://cloud.google.com/blog/)

- Solutions & technology
- [AI & Machine Learning](https://cloud.google.com/blog/products/ai-machine-learning)

- [API Management](https://cloud.google.com/blog/products/api-management)

- [Application Development](https://cloud.google.com/blog/products/application-development)

- [Application Modernization](https://cloud.google.com/blog/products/application-modernization)

- [Chrome Enterprise](https://cloud.google.com/blog/products/chrome-enterprise)

- [Compute](https://cloud.google.com/blog/products/compute)

- [Containers & Kubernetes](https://cloud.google.com/blog/products/containers-kubernetes)

- [Data Analytics](https://cloud.google.com/blog/products/data-analytics)

- [Databases](https://cloud.google.com/blog/products/databases)

- [DevOps & SRE](https://cloud.google.com/blog/products/devops-sre)

- [Maps & Geospatial](https://cloud.google.com/blog/topics/maps-geospatial)

- Security
- [Security & Identity](https://cloud.google.com/blog/products/identity-security)

- [Threat Intelligence](https://cloud.google.com/blog/topics/threat-intelligence)

- [Infrastructure](https://cloud.google.com/blog/products/infrastructure)

- [Infrastructure Modernization](https://cloud.google.com/blog/products/infrastructure-modernization)

- [Networking](https://cloud.google.com/blog/products/networking)

- [Productivity & Collaboration](https://cloud.google.com/blog/products/productivity-collaboration)

- [SAP on Google Cloud](https://cloud.google.com/blog/products/sap-google-cloud)

- [Storage & Data Transfer](https://cloud.google.com/blog/products/storage-data-transfer)

- [Sustainability](https://cloud.google.com/blog/topics/sustainability)

- Ecosystem
- [IT Leaders](https://cloud.google.com/transform)

- Industries
- [Financial Services](https://cloud.google.com/blog/topics/financial-services)

- [Healthcare & Life Sciences](https://cloud.google.com/blog/topics/healthcare-life-sciences)

- [Manufacturing](https://cloud.google.com/blog/topics/manufacturing)

- [Media & Entertainment](https://cloud.google.com/blog/products/media-entertainment)

- [Public Sector](https://cloud.google.com/blog/topics/public-sector)

- [Retail](https://cloud.google.com/blog/topics/retail)

- [Supply Chain](https://cloud.google.com/blog/topics/supply-chain-logistics)

- [Telecommunications](https://cloud.google.com/blog/topics/telecommunications)

- [Partners](https://cloud.google.com/blog/topics/partners)

- [Startups & SMB](https://cloud.google.com/blog/topics/startups)

- [Training & Certifications](https://cloud.google.com/blog/topics/training-certifications)

- [Inside Google Cloud](https://cloud.google.com/blog/topics/inside-google-cloud)

- [Google Cloud Next & Events](https://cloud.google.com/blog/topics/google-cloud-next)

- [Google Cloud Consulting](https://cloud.google.com/blog/topics/consulting)

- [Google Maps Platform](https://mapsplatform.google.com/resources/blog/)

- [Google Workspace](https://workspace.google.com/blog)

- [Developers & Practitioners](https://cloud.google.com/blog/topics/developers-practitioners)

- [Transform with Google Cloud](https://cloud.google.com/transform)

[Contact sales ](https://cloud.google.com/contact/)[Get started for free ](https://console.cloud.google.com/freetrial/)

Developers & Practitioners

# A developer's guide to Gemini Live API in Vertex AI

December 13, 2025

- [](https://x.com/intent/tweet?text=A%20developer%27s%20guide%20to%20Gemini%20Live%20API%20in%20Vertex%20AI%20@googlecloud&url=https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai)

- [](https://www.linkedin.com/shareArticle?mini=true&url=https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai&title=A%20developer%27s%20guide%20to%20Gemini%20Live%20API%20in%20Vertex%20AI)

- [](https://www.facebook.com/sharer/sharer.php?caption=A%20developer%27s%20guide%20to%20Gemini%20Live%20API%20in%20Vertex%20AI&u=https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai)

- [](mailto:?subject=A%20developer%27s%20guide%20to%20Gemini%20Live%20API%20in%20Vertex%20AI&body=Check%20out%20this%20article%20on%20the%20Cloud%20Blog:%0A%0AA%20developer%27s%20guide%20to%20Gemini%20Live%20API%20in%20Vertex%20AI%0A%0ALearn%20how%20to%20use%20Gemini%20Live%20API%20in%20Vertex%20AI%20to%20enable%20real-time,%20emotionally%20aware,%20and%20multimodal%20conversations%20in%20your%20applications.%0A%0Ahttps://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai)

##### Shubham Saboo
Senior AI Product Manager

##### Zack Akil
Developer Relations Engineer

##### Try Gemini Enterprise Business Edition today
The front door to AI in the workplace
[Try now ](https://business.gemini.google/?utm_source=cloud.google.com/blog&utm_medium=et&utm_campaign=FY26-Q2-GLOBAL-GLO27877-physicalevent-er-next26-mc-105752)

Give your AI apps and agents a natural, almost human-like interface, all through a single WebSocket connection. 

Today, [we announced](https://cloud.google.com/blog/products/ai-machine-learning/gemini-live-api-available-on-vertex-ai) the general availability of Gemini Live API on Vertex AI, which is powered by the latest Gemini 2.5 Flash Native Audio model. This is more than just a model upgrade; it represents a fundamental move away from rigid, multi-stage voice systems towards a single, real-time, emotionally aware, and multimodal conversational architecture.

We’re thrilled to give developers a deep dive into what this means for building the next generation of multimodal AI applications. In this post we'll look at two templates and three reference demos that help you understand how to best use Gemini Live API.

## Gemini Live API as your new voice foundation

For years, building conversational AI involved stitching together a high-latency pipeline of Speech-to-Text (STT), a Large Language Model (LLM), and Text-to-Speech (TTS). This sequential process created the awkward, turn-taking delays that prevented conversations from ever feeling natural.

Gemini  Live API fundamentally changes the engineering approach with a unified, low-latency, native audio architecture.

- Native audio processing: Gemini 2.5 Flash Native Audio model processes raw audio natively through a single, low-latency model. This unification is the core technical innovation that dramatically reduces latency.

- Real-time multimodality: The API is designed for unified processing across audio, text, and visual modalities. Your agent can converse about topics informed by live streams of visual data (like charts or live video feeds shared by a user) simultaneously with spoken input.

## Next-generation conversation features

Gemini Live API  gives you a suite of production-ready features that define a new standard for AI agents:

- Affective dialogue (emotional intelligence): By natively processing raw audio, the model can interpret subtle acoustic nuances like tone, emotion, and pace. This allows the agent to automatically de-escalate stressful support calls or adopt an appropriately empathetic tone.

- Proactive audio (smarter barge-in): This feature moves beyond simple Voice Activity Detection (VAD). As demonstrated in our live demo, you can configure the agent to intelligently decide when to respond and when to remain a silent co-listener. This prevents unnecessary interruptions when passive listening is required, making the interaction feel truly natural.

- Tool use: Developers can seamlessly integrate tools like Function Calling and Grounding with Google Search into these real-time conversations, allowing agents to pull real-time world knowledge and execute complex actions immediately based on spoken and visual input.

- Continuous memory: Agents maintain long, continuous context across all modalities.

- Enterprise-grade stability: With GA release, you get the high availability required for production workloads, including multi-region support to ensure your agents remain responsive and reliable for users globally.

## Developer quickstart: Getting started

For developers, the quickest way to experience the power of low-latency, real-time audio is to understand the flow of data. Unlike REST APIs where you make a request and wait, Gemini Live API requires managing a bi-directional stream.

### Gemini Live API flow

Before diving into code, it is critical to visualize the production architecture. While a direct connection is possible for prototyping, most enterprise applications require a secure, proxied flow: User-facing App -> Your Backend Server -> Gemini Live API (Google Backend).

In this architecture, your frontend captures media (microphone/camera) and streams it to your secure backend, which then manages the persistent WebSocket connection to Gemini Live API in Vertex AI. This ensures sensitive credentials never leave your server and allows you to inject business logic, persist conversation state, or manage access control before data flows to Google.

​​To help you get started, we have released two distinct Quickstart templates - one for understanding the raw protocol, and one for modern component-based development.

### Option A: [Vanilla JS Template (zero dependency)](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/plain-js-demo-app)

Best for: Understanding the raw WebSocket implementation and media handling without framework overhead.

This template handles the WebSocket handshakes and media streaming, giving you a clean slate to build your logic.

Project Structure:

Loading...

/
├── server.py # WebSocket proxy + HTTP server
└── frontend/
├── geminilive.js # Gemini API client wrapper
├── mediaUtils.js # Audio/video streaming logic
└── script.js # App logic

Core implementation: You interact with the gemini-live-2.5-flash-native-audio model via a stateful WebSocket connection.

Loading...

const client = new GeminiLiveAPI(proxyUrl, projectId, model);

// Connect using the access token handled by the proxy
client.connect(accessToken); 

// Stream audio from the user's microphone
client.sendAudioMessage(base64AudioChunk);

Running the Vanilla JS Demo:

Loading...

pip3 install -r requirements.txt
gcloud auth application-default login
python3 server.py
# Open http://localhost:8000

Follow along the step-by-step video [walkthrough](https://www.youtube.com/watch?v=RLM1Qsp64WU).

Pro-tip: Debugging raw audio Working with raw PCM audio streams can be tricky. If you need to verify your audio chunks or test Base64 strings, we’ve included a [PCM Audio Debugger](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/pcm-audio-debugger) in the repository.

### Option B: [React demo (modular & modern)](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/react-demo-app)

Best for: Building scalable, production-ready applications with complex UIs.

If you are building a robust enterprise application, our React starter provides a modular architecture using AudioWorklets for high-performance, low-latency audio processing.

Features:

- Real-time streaming: Audio and video streaming to Gemini with React state management.

- AudioWorklets: Uses capture.worklet.js and playback.worklet.js for dedicated audio processing threads.

- Secure proxy: Python backend handles Google Cloud authentication.

Project structure:

Loading...

/
├── server.py # WebSocket proxy & auth handler
├── src/
│ ├── components/
│ │ └── LiveAPIDemo.jsx # Main UI logic
│ └── utils/
│ │ ├── gemini-api.js # Gemini WebSocket client
│ │ └── media-utils.js # Audio/Video processing
└── public/
└── audio-processors/ # Audio worklets

Running the react demo:

Loading...

# Terminal 1: Start the Backend
pip install -r requirements.txt
gcloud auth application-default login
python server.py

# Terminal 2: Start the Frontend
npm install
npm run dev
# Open http://localhost:5173

Follow along the step-by-step video [walkthrough](https://youtu.be/wCrz8tw6xXs?si=qNuEv6eJzkgWsDag).

### Partner Integrations

If you prefer a simpler development process for specific telephony or WebRTC environments, we have third-party partner integrations with [Daily](https://docs.pipecat.ai/server/services/s2s/gemini-live-vertex), [Twilio](https://www.twilio.com/docs), [LiveKit](https://docs.livekit.io/agents/models/realtime/plugins/gemini/), and [Voximplant](https://voximplant.com/products/gemini-client). These platforms have integrated the Gemini Live API over the WebRTC protocol, allowing you to drop these capabilities directly into your existing voice and video workflows without managing the networking stack yourself .

## Gemini Live API: Three production-ready demos

Once you have your foundation set with either template, how do you scale this into a product? We’ve built three demos showcasing the distinct "superpowers" of Gemini Live API.

### 1. Real-time proactive advisor agent

The core of building truly natural conversational AI lies in creating a partner, not just a chatbot. This specialized application demonstrates how to build a business advisor that listens to a conversation and provides relevant insights based on a provided knowledge base.

It showcases two critical capabilities for professional agents: Dynamic Knowledge Injection and Dual Interaction Modes.

- 
The Scenario: An advisor sits in on a business meeting. It has access to specific injected data (revenue stats, employee counts) that the user defines in the UI.

- 
Dual modes:

- 
Silent mode: The advisor listens and "pushes" visual information via a show_modal tool without speaking. This is perfect for unobtrusive assistance where you want data, not interruption.

- 
Outspoken mode: The advisor politely interjects verbally to offer advice, combining audio response with visual data.

- 
Barge-in control: The demo uses activity_handling configurations to prevent the user from accidentally interrupting the advisor, ensuring complete delivery of complex advice when necessary.

- Tool use: Uses a custom show_modal tool to display structured information to the user.

Check out the full source code for the real-time advisor agent implementation in our [GitHub repository](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/realtime-advisor-demo-app).

### 2. Multimodal customer support agent

Customer support agents must be able to act on what they "see" and "hear." This demo layers Contextual Action and Affective Dialogue onto the voice stream, creating a support agent that can resolve issues instantly.

This application simulates a futuristic customer support interaction where the agent can see what you see, understand your tone, and take real actions to resolve your issues instantly. Instead of describing an item for a return, the user simply shows it to the camera. The agent combines this visual input with emotional understanding to drive real actions:

- Multimodal Understanding: The agent visually inspects items shown by the customer (e.g., verifying a product for return) while listening to their request.

- Empathetic Response: Using affective dialogue, the agent detects the user's emotional state (frustration, confusion) and adjusts its tone to respond with appropriate empathy.

- Action Taking and Tool Use: It doesn't just chat; it uses custom tools like process_refund (handling transaction IDs) or connect_to_human (transferring complex issues) to actually solve the problem.

- Real-time Interaction: Low-latency voice interaction using Gemini Live API over WebSockets.

Check out the full source code for the multi-modal customer support agent implementation in our [GitHub repository](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/customer-support-demo-app).

### 3. Real-time video game assistant

Gaming is better with a co-pilot. In this demo, we build a Real-Time Gaming Guide that moves beyond simple chat to become a true companion that watches your gameplay and adapts to your style.

This React application streams both your screen capture and microphone audio to the model simultaneously, allowing the agent to understand the game state instantly. It showcases three advanced capabilities:

- Multimodal awareness: The agent acts as a second pair of eyes, analyzing your screen to spot enemies, loot, or puzzle clues that you might miss.

- Persona switching: You can dynamically toggle the agent's personality - from a "Wise Wizard" offering cryptic hints to a "SciFi Robot" or "Commander" giving tactical orders. This demonstrates how system instructions can instantly change the voice and style of assistance.

- Google Search Grounding: The agent pulls real-time information to provide up-to-date walkthroughs and tips, ensuring you never get stuck on a new level.

Check out the full source code for the real-time video game assistant implementation in our [GitHub repository](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/gaming-assistant-demo-app).

## Get started today 

- Try it out today: Experiment with Gemini Live API in [Vertex AI Studio](https://console.cloud.google.com/vertex-ai/studio/multimodal-live)

- Start building: Access [Gemini Live API on Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api) today and move beyond chatbots to create truly intelligent, responsive, and empathetic user experiences.

- Get the code: All demos and quickstarts are available in our official [GitHub repository](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api).

Posted in
- [Developers & Practitioners](https://cloud.google.com/blog/topics/developers-practitioners)

- [AI & Machine Learning](https://cloud.google.com/blog/products/ai-machine-learning)

##### Related articles
[

Developers & Practitioners

### Introducing the Developer Device Platform for agentic mobile app development
By Derek Bekebrede • 3-minute read

](https://cloud.google.com/blog/topics/developers-practitioners/announcing-developer-device-platform-on-google-cloud)

[

Networking

### ClusterNetworkPolicy in GKE: Balancing control and autonomy for your microservices
By Srini Jasti • 4-minute read

](https://cloud.google.com/blog/products/networking/new-clusternetworkpolicy-in-gke)

[

Developers & Practitioners

### Behind the scenes: How we build, test, and scale Google Agent Skills
By Remigiusz Samborski • 6-minute read

](https://cloud.google.com/blog/topics/developers-practitioners/behind-the-scenes-how-we-build-test-and-scale-google-agent-skills)

[

Developers & Practitioners

### Automate your agent development lifecycle using any coding agent
By Shubham Saboo • 7-minute read

](https://cloud.google.com/blog/topics/developers-practitioners/automate-agent-development-lifecycles-with-gemini-enterprise)

### Footer Links

#### Follow us

- [](https://www.x.com/googlecloud)

- [](https://www.youtube.com/googlecloud)

- [](https://www.linkedin.com/showcase/google-cloud)

- [](https://www.instagram.com/googlecloud/)

- [](https://www.facebook.com/googlecloud/)

[](https://cloud.google.com/)

- [Google Cloud](https://cloud.google.com/)

- [Google Cloud Products](https://cloud.google.com/products/)

- [Privacy](https://myaccount.google.com/privacypolicy?hl=en-US)

- [Terms](https://myaccount.google.com/termsofservice?hl=en-US)

- [Cookies management controls](#)

- [Help](https://support.google.com)

- Language‪English‬‪Deutsch‬‪Français‬‪한국어‬‪日本語‬