import openai 
from flask import current_app
# No Pinecone-specific utilities needed anymore.
# No client-side embedding generation utility needed here if Chroma handles it.

def query_llm_groq(prompt, system_message=None, model_name=None, temperature=0.7, max_tokens=500):
    """Queries an LLM via Groq API."""
    try:
        api_key = current_app.config.get('GROQ_API_KEY')
        if not api_key or api_key == "YOUR_GROQ_API_KEY":
            current_app.logger.error("Groq API key not configured or is a placeholder.")
            return "Error: Groq API key not configured."

        client = openai.OpenAI(
            base_url="https://api.groq.com/openai/v1", 
            api_key=api_key,
        )
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        chat_model = model_name or current_app.config['CHAT_MODEL_GROQ']
        
        response = client.chat.completions.create(
            model=chat_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        current_app.logger.error(f"Error querying LLM from Groq model {chat_model}: {e}")
        return f"Error: Could not get response from LLM. Details: {str(e)}"
