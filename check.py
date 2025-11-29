import os
from dotenv import load_dotenv
from tavily import TavilyClient
from langchain_openai import ChatOpenAI

load_dotenv()

try:
    llm = ChatOpenAI(
    model="openai/gpt-oss-20b:free",
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1"

    )
    response = llm.invoke("Say 'Hello, I am connected to OpenRouter!'")
    print(f"The response is {response.content}")
except:
    print("OpenRouter no work :(")


try:
    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    results = tavily.search(query="What is the capital of France?", max_results=1)
    print(f"Tavily Success: Found {len(results['results'])} result")
except Exception as e:
    print(f"❌ Tavily Failed: {e}")
