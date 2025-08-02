from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool
from dotenv import load_dotenv

load_dotenv()

@tool
def simple_test_tool(message: str) -> str:
    """A simple test tool that echoes back the message."""
    return f"Echo: {message}"

def test_groq_function_calling():
    """Test if Groq function calling works with a simple tool."""
    
    # Define tools
    tools = [simple_test_tool]
    
    # Simple prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant. Use the available tool to echo the user's message."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    
    # Initialize LLM
    llm = ChatGroq(model_name="llama3-8b-8192", temperature=0)
    
    # Create agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    
    # Test
    try:
        result = agent_executor.invoke({"input": "Hello, this is a test message"})
        print("SUCCESS:", result)
        return True
    except Exception as e:
        print("ERROR:", e)
        return False

if __name__ == "__main__":
    test_groq_function_calling()
