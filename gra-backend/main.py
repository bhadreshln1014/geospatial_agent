import sys
import os
from agent import setup_agent

def main():
    """
    Main function to run the Geospatial Reasoning Agent.
    Takes a natural language query as a command-line argument.
    """
    # Create output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)

    # Check for query argument
    if len(sys.argv) < 2:
        print("="*50)
        print("Geospatial Reasoning Agent (GRA)")
        print("="*50)
        print("Usage: python main.py \"Your geospatial query in quotes\"")
        print("\nExample: python main.py \"Find the best areas for a new school in Palo Alto, CA. It should be away from bars and on flat land.\"")
        sys.exit(1)

    # Combine arguments into a single query string
    query = " ".join(sys.argv[1:])
    print(f"▶️  Processing query: \"{query}\"\n")

    # Setup and run the agent
    try:
        gra_agent = setup_agent()
        result = gra_agent.invoke({"input": query})

        print("\n" + "✅" * 25)
        print("✅ Agent execution complete!")
        print(f"✅ Final map saved to: {result['output']}")
        print("✅ You can now open this file in a GIS software like QGIS.")
        print("✅" * 25)

    except Exception as e:
        print(f"\n❌ An error occurred during agent execution: {e}")
        print("❌ Please check your query, API keys, and tool implementations.")

if __name__ == "__main__":
    main()
