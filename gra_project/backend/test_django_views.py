#!/usr/bin/env python3
"""
Test script for the Django streaming view.
This simulates HTTP requests to test the streaming functionality.
"""

import requests
import json
import time


def test_streaming_endpoint():
    """Test the streaming endpoint with a sample query."""
    print("🧪 Testing Django Streaming Endpoint")
    print("=" * 50)
    
    # Sample queries to test
    test_queries = [
        "Find suitable areas for affordable housing in Palo Alto considering proximity to schools and avoiding noisy areas",
        "Analyze temperature patterns in Chennai for urban planning",
        "What are the best locations for parks in Davis considering elevation and existing amenities?"
    ]
    
    url = "http://localhost:8000/agent_app/stream_query_agent/"  # Adjust URL as needed
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{i}. Testing query: '{query}'")
        print("-" * 40)
        
        try:
            # Prepare the request
            payload = {"query": query}
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            }
            
            # Send streaming request
            response = requests.post(url, 
                                   data=json.dumps(payload), 
                                   headers=headers, 
                                   stream=True, 
                                   timeout=300)  # 5 minute timeout
            
            if response.status_code == 200:
                print("✅ Connection established, streaming events:")
                
                event_count = 0
                for line in response.iter_lines(decode_unicode=True):
                    if line.startswith('data: '):
                        event_count += 1
                        try:
                            event_data = json.loads(line[6:])  # Remove 'data: ' prefix
                            event_type = event_data.get('type', 'unknown')
                            message = event_data.get('message', '')
                            
                            # Truncate long messages for readability
                            if len(str(message)) > 100:
                                message = str(message)[:97] + "..."
                            
                            print(f"   📡 Event {event_count}: {event_type} - {message}")
                            
                            # If this is the completion event, show summary
                            if event_type == 'complete':
                                final_result = event_data.get('final_map_result')
                                if final_result:
                                    print(f"   🗺️  Final Map Result: {final_result}")
                                break
                                
                        except json.JSONDecodeError:
                            print(f"   ⚠️  Could not parse event: {line}")
                
                print(f"✅ Test completed. Received {event_count} events.")
                
            else:
                print(f"❌ HTTP Error {response.status_code}: {response.text}")
                
        except requests.exceptions.ConnectionError:
            print("❌ Connection failed. Make sure Django server is running on localhost:8000")
        except requests.exceptions.Timeout:
            print("❌ Request timed out. The agent might be taking too long to process.")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Wait between tests
        if i < len(test_queries):
            print("⏳ Waiting 5 seconds before next test...")
            time.sleep(5)


def test_output_files_endpoint():
    """Test the output files endpoint."""
    print("\n🗂️  Testing Output Files Endpoint")
    print("=" * 40)
    
    url = "http://localhost:8000/agent_app/get_output_files/"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            files = data.get('files', [])
            print(f"✅ Found {len(files)} output files:")
            for file_info in files:
                print(f"   📄 {file_info['name']} ({file_info['type']}, {file_info['size']} bytes)")
        else:
            print(f"❌ HTTP Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Run the Django view tests."""
    print("🚀 Testing Geospatial Agent Django Views")
    print("Make sure Django server is running: python manage.py runserver\n")
    
    # Test streaming endpoint
    test_streaming_endpoint()
    
    # Test output files endpoint
    test_output_files_endpoint()
    
    print("\n" + "=" * 60)
    print("DJANGO TESTING COMPLETE")
    print("=" * 60)
    print("If you see ✅ marks above, the Django integration is working!")
    print("If you see ❌ marks, check:")
    print("1. Django server is running: python manage.py runserver")
    print("2. URLs are correctly configured")
    print("3. All dependencies are installed")


if __name__ == "__main__":
    main()
