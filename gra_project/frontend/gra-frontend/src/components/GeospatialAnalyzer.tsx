'use client'
import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';

// Dynamically import map component to avoid SSR issues
const MapViewer = dynamic(() => import('./MapViewer'), { ssr: false });

interface CoTMessage {
  type: string;
  message: string;
  tool?: string;
  step?: number;
  timestamp?: number;
  output_files?: string[];
  total_steps?: number;
}

export default function GeospatialAnalyzer() {
  const [query, setQuery] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [messages, setMessages] = useState<CoTMessage[]>([]);
  const [outputFiles, setOutputFiles] = useState<string[]>([]);

  // Debug outputFiles changes
  useEffect(() => {
    console.log('GeospatialAnalyzer: outputFiles updated:', outputFiles);
  }, [outputFiles]);

  const startAnalysis = async () => {
    if (!query.trim()) return;
    
    setIsAnalyzing(true);
    setMessages([]);
    setOutputFiles([]);

    try {
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8001';
      const response = await fetch(`${apiBaseUrl}/api/stream_query/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
      });

      if (!response.body) throw new Error('No response body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              setMessages(prev => [...prev, data]);
              
              if (data.type === 'complete' && data.output_files) {
                setOutputFiles(data.output_files);
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e);
            }
          }
        }
      }
    } catch (error) {
      console.error('Analysis error:', error);
      setMessages(prev => [...prev, {
        type: 'error',
        message: '❌ Analysis failed. Please try again.'
      }]);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getMessageIcon = (type: string) => {
    switch (type) {
      case 'start': return '🚀';
      case 'phase': return '📋';
      case 'tool_start': return '🛠️';
      case 'tool_complete': return '✅';
      case 'complete': return '🎉';
      case 'error': return '❌';
      default: return '💭';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold text-center mb-8 text-gray-800">
          🌍 Geospatial Reasoning Agent
        </h1>
        
        {/* Query Input */}
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="flex gap-4">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask me about geospatial analysis... (e.g., 'Find the best areas for a school in Palo Alto')"
              className="flex-1 p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              disabled={isAnalyzing}
            />
            <button
              onClick={startAnalysis}
              disabled={isAnalyzing || !query.trim()}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {isAnalyzing ? '🔄 Analyzing...' : '🚀 Start Analysis'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Chain of Thought Display */}
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-2xl font-semibold mb-4 text-gray-800">
              🧠 Chain of Thought
            </h2>
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {messages.length === 0 && !isAnalyzing && (
                <p className="text-gray-500 italic">
                  Chain-of-thought will appear here during analysis...
                </p>
              )}
              {messages.map((msg, idx) => (
                <div key={idx} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                  <span className="text-xl">{getMessageIcon(msg.type)}</span>
                  <div className="flex-1">
                    <p className="text-gray-800">{msg.message}</p>
                    {msg.timestamp && (
                      <p className="text-xs text-gray-500 mt-1">
                        {new Date(msg.timestamp * 1000).toLocaleTimeString()}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Map Viewer */}
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-2xl font-semibold mb-4 text-gray-800">
              🗺️ Results Map
            </h2>
            {outputFiles.length > 0 ? (
              <div>
                <MapViewer outputFiles={outputFiles} />
                <div className="mt-4">
                  <h3 className="font-semibold mb-2">Generated Files:</h3>
                  <ul className="space-y-1">
                    {outputFiles.map((file, idx) => (
                      <li key={idx} className="text-sm text-blue-600 flex items-center justify-between">
                        <span>📄 {file}</span>
                        {/* Add a helpful hint for raster files */}
                        {file.endsWith('.tif') && (
                          <span className="text-xs font-medium bg-yellow-100 text-yellow-800 px-2 py-1 rounded-full">
                            View in QGIS/ArcGIS
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <div className="h-64 bg-gray-100 rounded-lg flex items-center justify-center">
                <p className="text-gray-500">Map will appear here after analysis</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
