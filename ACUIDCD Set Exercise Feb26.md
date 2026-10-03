Advanced Conversational UI Design and Chatbot Development

Overview
This assignment develops your theoretical and practical competencies in designing, constructing, and deploying an
advanced conversational system for sustainable tourism planning. The case study focuses on a chatbot that assists
travelers in planning eco-friendly trips by recommending sustainable accommodations, low-carbon transportation
options, carbon offset initiatives, and local cultural experiences that support communities. You will apply modern
conversational UI/UX principles, advanced NLP techniques, and the Rasa framework to create a robust system that
promotes responsible travel while accommodating diverse user preferences.
Learning Outcomes:
LO1. Innovate conversational UI design, integrate cutting-edge interaction design principles, and demonstrate the
ability to create chatbots that adapt to evolving user needs
LO2. Conduct in-depth research on the latest trends in conversational UI design, critically analyze the impact of AI,
NLP, as well as user experience principles, and identify opportunities for improvement in chatbot design and
development
LO3. Demonstrate professional expertise in UI design and chatbot development through the creation of context-
aware, user-centric chatbots and effective communication of design rationale and outcomes to stakeholders
Assessment Criteria: Weighting 100%
3000 words
Assignment Goals
Objective
Design and implement a conversational agent capable of supporting travelers in planning environmentally responsible
trips. The system must:

1. Provide recommendations on sustainable accommodation, transport, and activities based on user preferences
   and location.
2. Calculate and present approximate carbon footprints for travel options to guide decision-making.
3. Perform multi-turn questioning to refine user needs (dates, budget, sustainability goals).
4. Escalate complex planning cases to human travel advisors, supplying them with full conversational context.

5. Operate ethically and transparently, especially concerning environmental claims, data privacy, and accessibility.
   Scope
   Your chatbot must support:
   � Trip planning through adaptive multi?turn dialogues that elicit destinations, travel dates, budgets, and
   sustainability preferences.
   � Retrieval of structured information on eco-certified hotels, green transport options, cultural experiences, and
   carbon offset programs.
   � Location?based updates (e.g., carbon emissions data or availability of public transport) using GPS or manual
   location input.
   � Context?aware suggestions that balance environmental impact with user constraints.
   � Seamless handover to human travel specialists for itineraries that require expert intervention.
   Intended Outcomes
   � Empower travelers to make informed, sustainable choices when planning trips.
   � Encourage adoption of eco?friendly tourism practices and reduce the environmental impact of travel.
   � Demonstrate mastery of conversational system design and Rasa implementation in a novel domain.
   � Foster interdisciplinary thinking by integrating environmental science data with AI and UX design.

Assignment Tasks

1. Conducting In?Depth Research
   Perform a structured literature review covering: state?of?the?art sustainable travel chatbots (industry and academia);
   the use of NLP, multimodal inputs, and LLMs in travel and environmental communication; user experience and
   persuasive design considerations for promoting behavior change; and ethical concerns such as greenwashing, data
   privacy, accessibility, and inclusivity. Your analysis must identify current gaps in sustainable travel assistance,
   opportunities for innovation, and potential risks or limitations.
2. Analysis of Functional and Non?Functional Requirements
   Functional Requirements
   Your system must include at minimum:
   � Trip intake module with adaptive questioning that gathers destination, dates, budget, and sustainability
   preferences.
   � Location detection via manual input or GPS integration to tailor recommendations.
   � Verified information retrieval from databases or APIs that list eco?certified accommodations, public
   transportation schedules, carbon calculators, and cultural events.
   � Human advisor escalation module with full context handover for complex itineraries or when users request
   personalized consultation.
   � Error recovery mechanisms that handle incomplete or ambiguous messages and clarify user intent.
   Non?Functional Requirements
   Include considerations such as:
   � Usability: clear conversational language, helpful tooltips explaining sustainability metrics, and minimal cognitive
   load.
   � Reliability: consistent behavior under varying user loads and across different devices.
   � Response latency: under three seconds for critical interactions.
   � Accessibility: screen?reader friendliness.
   � Data privacy: compliance with GDPR and respectful handling of personal and travel data.
3. Creation of Conversational Prototype and User Interaction Design
   � Use tools such as Figma, Miro, Lucidchart, or Rasa Webchat to visualize conversation flows and integration
   points with external services (e.g., carbon footprint APIs).
   � Develop a high?fidelity prototype illustrating full dialogue flows for several travel scenarios (e.g., short city
   break, eco?tour in rural area, carbon?neutral business trip, etc.,). Show branching logic that adapts based on
   sustainability preferences and budget.
   � Design user interface elements such as:

o Quick-reply buttons for selecting destinations
o Carousels displaying eco?friendly hotels
o Alert messages highlighting high?emission options
o Clear indications of human handover 4. Programming Work, AI, and NLP Techniques
Technical Implementation
� Implement a complete chatbot using Rasa Open Source (NLU + Core).
� Develop custom actions in actions.py to handle the following responsibilities:
o Querying the Climatiq API for real-time carbon emission calculations per transport mode
o Fetching hotel and flight data from the Amadeus for Developers sandbox API
o Ranking retrieved options by a weighted scoring function that combines carbon impact, price, and user-
stated preferences
o Packaging full conversation context for human advisor handover.
Each action must include error-handling for failed API responses and fallback messaging.
� For NLU, begin with Rasa's default DIETClassifier pipeline (spaCy tokeniser + featurisers), which offers the best
balance of accuracy and response speed on CPU-hosted environments. If inference latency remains comfortably
under 3 seconds in your deployment environment, you may optionally swap in a DistilBERT-based pipeline
using a HuggingFace pretrained model via the HFTransformersNLP component.
� Manage conversation state through Rasa stories and rules, using slots to persist user-provided values
(destination, travel dates, budget, sustainability preference level) across turns. Implement a dedicated fallback
rule using action_default_fallback and a two-stage clarification flow that re-prompts the user with constrained
options (quick-reply buttons) before escalating to the human handover action.
Frontend
Build the chat interface using either Rasa Webchat (the simplest integration path, requiring only a script embed and
basic CSS overrides) or ReactJS with the Rasa REST channel for a more custom implementation. Streamlit is an
acceptable lightweight alternative for a prototype-focused submission but is not recommended for production-quality
UI work.
The interface must include the following concrete UI elements wired to real bot data: quick-reply buttons generated
dynamically from custom action responses for destination and preference selection; a colour-coded results card (green
for low-emission options, amber for moderate, red for high) driven by the carbon score returned from the Climatiq API;
and a human handover indicator that visually signals when the conversation has been escalated.
Optional: Ensure that the interface supports multiple languages and provides alternative interaction modes (text or
voice).

5. Testing
   � Critically assess your chatbot�s performance along several dimensions: NLU accuracy,
   recommendation quality (e.g., alignment with sustainability criteria), UI/UX effectiveness, technical
   robustness, compliance with privacy regulations, environmental ethics, and inclusivity.
   Rasa NLU Testing
   � Use commands such as `rasa test nlu` to evaluate the accuracy of intent classification and entity
   extraction. Analyse confusion matrices and use cross?validation to improve your model.
   Dialogue Testing
   � Run `rasa test core` to assess story transitions, edge?case handling, and fallback performance. Extend
   test stories to cover variations in user requests and sustainability preferences.
   User Testing
   � If possible, conduct usability testing with a small group of potential travelers. Collect feedback on
   clarity, persuasiveness of sustainability recommendations, and overall user experience. Measure
   perceived trust and ease?of?use through surveys or interviews and incorporate insights into your final
   evaluation.
6. Deployment
   Deployment Process
   Prepare step?by?step deployment documentation that includes containerization using Docker; cloud
   deployment to platforms like AWS, Azure, GCP, or HuggingFace Spaces; environment variables and
   configuration management; and secure endpoint handling. You may also use tools such as Pyngrok for secure
   tunnelling during development and testing.
   Recommendation: For hosting, HuggingFace Spaces (Docker SDK) is the most practical zero-cost option for
   this assignment and is fully sufficient for demonstration purposes.
   Grading Criteria
   � Project Goals & Requirements Clarity � 15%
   � Research and Trend Analysis Depth � 15%
   � Prototype & Interaction Design Quality � 20%
   � Technical Implementation & NLP Integration � 20%
   � Testing Robustness � 15%
   � Deployment & Professional Documentation � 15%

Submission Guidelines
Prepare a comprehensive report showcasing your chatbot design, implementation, and evaluation:
� Include screenshots or embedded visuals illustrating conversation flows, UI designs, model
architecture, training progress, and evaluation metrics.
� Ensure all code is well-commented with clear replication instructions.
� Your report must be clear, organized, and visually appealing, using the BSBI assignment
template available on Canvas.
� Upload your submission as a single file (PDF or DOC).
� Python scripts or Jupyter notebooks should be uploaded to a repository platform (e.g.,
GitHub) with a shared link included.
� Cite all sources using the Harvard Referencing System.
� Submit your assignment electronically by the specified deadline.
