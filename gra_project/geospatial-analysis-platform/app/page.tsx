"use client"

import { useState, useEffect, useRef } from "react"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Plus, Upload, Play, FileText, Map, Settings, Loader2, CheckCircle, AlertCircle } from "lucide-react"
import { useToast } from "@/hooks/use-toast"
import dynamic from "next/dynamic"
import { apiService, API_BASE_URL } from "@/lib/api" // NEW IMPORT

// Dynamically import Monaco Editor to avoid SSR issues
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false })

// Dynamically import Map Component to avoid SSR issues
const MapComponent = dynamic(() => import("@/components/map-component"), { ssr: false })

// --- NEW: API-aligned types ---
interface Thread {
  id: string
  title: string
  created_at: string
}

interface ThreadMessage {
    id: string;
    user_query?: string;
    agent_explanation?: string;
    agent_workflow_plan?: AgentWorkflowPlan;
    execution_log?: any[]; // Can be more specific if you have a type for log entries
    final_map_result?: MapResult;
    timestamp: string;
}


interface UserDataLayer {
  id: string
  name: string
  data_type: "Vector" | "Raster"
  file_path: string // This will be a server path, not directly used by frontend
  thread_id: string
}

interface WorkflowStep {
  step_id: string // Or step_num from the backend
  tool_name: string
  reasoning: string
  parameters: Record<string, any>
}

interface AgentWorkflowPlan {
  overall_reasoning: string
  plan: WorkflowStep[]
  expected_output: string
}

interface MapResult {
  url: string;
  type: 'vector' | 'raster';
  bbox: [number, number, number, number] | null;
  name: string;
}

// Mock data
const mockThreads: Thread[] = [
  {
    id: "thread_1",
    title: "Jaipur Solar Farm Siting",
    created_at: "2024-01-15T10:30:00Z",
  },
  {
    id: "thread_2",
    title: "Mumbai Flood Risk Analysis",
    created_at: "2024-01-14T14:20:00Z",
  },
  {
    id: "thread_3",
    title: "Delhi Air Quality Mapping",
    created_at: "2024-01-13T09:15:00Z",
  },
]

const mockDataLayers: UserDataLayer[] = [
  {
    id: "layer_1",
    name: "Jaipur Elevation",
    data_type: "Raster",
    file_path: "/data/jaipur_dem.tif",
    thread_id: "thread_1",
  },
  { id: "layer_2", name: "Road Network", data_type: "Vector", file_path: "/data/roads.geojson", thread_id: "thread_1" },
  { id: "layer_3", name: "Land Use", data_type: "Vector", file_path: "/data/landuse.shp", thread_id: "thread_1" },
]

const mockWorkflowPlan: AgentWorkflowPlan = {
  overall_reasoning:
    "To find suitable solar farm locations, I'll analyze slope from elevation data, buffer roads for accessibility, reclassify land use for suitable areas, and combine all factors using weighted overlay analysis.",
  plan: [
    {
      step_id: "step_1",
      tool_name: "calculate_slope",
      reasoning: "Calculate slope from elevation data to identify areas with suitable gradient for solar installations",
      parameters: {
        input_raster: "jaipur_elevation",
        output_name: "slope_analysis",
        slope_units: "degrees",
      },
    },
    {
      step_id: "step_2",
      tool_name: "perform_buffer",
      reasoning: "Create buffer zones around roads to ensure accessibility for construction and maintenance",
      parameters: {
        input_vector: "road_network",
        buffer_distance: 1000,
        output_name: "road_buffers",
      },
    },
    {
      step_id: "step_3",
      tool_name: "reclassify_raster",
      reasoning: "Reclassify slope values to suitability scores (0-5 degrees = suitable)",
      parameters: {
        input_raster: "slope_analysis",
        reclassification: [
          [0, 5, 1],
          [5, 15, 0.5],
          [15, 90, 0],
        ],
        output_name: "slope_suitability",
      },
    },
    {
      step_id: "step_4",
      tool_name: "weighted_overlay",
      reasoning: "Combine all suitability factors with appropriate weights to generate final suitability map",
      parameters: {
        input_layers: ["slope_suitability", "road_buffers", "landuse_suitable"],
        weights: [0.4, 0.3, 0.3],
        output_name: "solar_suitability_final",
      },
    },
  ],
  expected_output:
    "A raster map showing solar farm suitability scores from 0-1, with higher values indicating more suitable locations",
}

export default function GeospatialAnalysisPlatform() {
  const [activeThread, setActiveThread] = useState<Thread | null>(null)
  const [threads, setThreads] = useState<Thread[]>([])
  const [dataLayers, setDataLayers] = useState<UserDataLayer[]>([])
  const [userQuery, setUserQuery] = useState("")
  const [workflowPlan, setWorkflowPlan] = useState<AgentWorkflowPlan | null>(null)
  const [isAdvancedMode, setIsAdvancedMode] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [executionLog, setExecutionLog] = useState<any[]>([])
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false)
  const [mapResult, setMapResult] = useState<MapResult | null>(null)
  const { toast } = useToast()
  const monacoEditorRef = useRef<any>(null)
  const stepEditorsRef = useRef<{ [key: string]: any }>({})
  const [jsonValidationErrors, setJsonValidationErrors] = useState<{ [key: string]: string }>({})
  const [showDataLayers, setShowDataLayers] = useState(false)
  const [activeMessage, setActiveMessage] = useState<ThreadMessage | null>(null);


  // Fetch all threads on initial load
  useEffect(() => {
    const fetchThreads = async () => {
      try {
        const threadsData = await apiService<Thread[]>('/threads/');
        setThreads(threadsData);
        if (threadsData.length > 0) {
          setActiveThread(threadsData[0]);
        }
      } catch (error) {
        toast({ title: "Error", description: "Could not fetch analysis threads.", variant: "destructive" });
      }
    };
    fetchThreads();
  }, [toast]);


  // Load active thread data
  useEffect(() => {
    const fetchThreadDetails = async () => {
      if (activeThread) {
        try {
          // Fetch the last message for the thread to get the latest state
          const messages = await apiService<ThreadMessage[]>(`/threads/${activeThread.id}/messages/`);
          const lastMessage = messages[messages.length - 1];
          
          if (lastMessage) {
            setActiveMessage(lastMessage);
            setUserQuery(lastMessage.user_query || "");
            setWorkflowPlan(lastMessage.agent_workflow_plan || null);
            setExecutionLog(lastMessage.execution_log || []);
            setMapResult(lastMessage.final_map_result || null);
            // Clear JSON validation errors when switching threads
            setJsonValidationErrors({});
          } else {
            // Reset fields if there are no messages
            setActiveMessage(null);
            setUserQuery("");
            setWorkflowPlan(null);
            setExecutionLog([]);
            setMapResult(null);
            setJsonValidationErrors({});
          }

          // Fetch data layers associated with the thread
          const layers = await apiService<UserDataLayer[]>(`/threads/${activeThread.id}/layers/`);
          setDataLayers(layers);

        } catch (error) {
          toast({ title: "Error", description: `Could not fetch details for thread: ${activeThread.title}`, variant: "destructive" });
        }
      }
    };
    fetchThreadDetails();
  }, [activeThread, toast]);

  const handleNewAnalysis = async () => {
    try {
        const newThread = await apiService<Thread>('/threads/', {
            method: 'POST',
            body: JSON.stringify({ title: 'New Analysis' }),
        });
        setThreads([newThread, ...threads]);
        setActiveThread(newThread);
        // Resetting UI state for the new thread
        setUserQuery("");
        setWorkflowPlan(null);
        setMapResult(null);
        setExecutionLog([]);
        setDataLayers([]);
        setActiveMessage(null);
    } catch (error) {
        toast({ title: "Error", description: "Failed to create a new analysis thread.", variant: "destructive" });
    }
  }

  const handleGeneratePlan = async () => {
    if (!userQuery.trim() || !activeThread) return

    setIsGeneratingPlan(true)
    try {
      const planData = await apiService<ThreadMessage>('/plan/', {
        method: 'POST',
        body: JSON.stringify({
          thread_id: activeThread.id,
          query: userQuery,
        }),
      });
      setWorkflowPlan(planData.agent_workflow_plan || null);
      setActiveMessage(planData);
      toast({
        title: "Plan Generated",
        description: "Workflow plan has been generated successfully.",
      })
    } catch (error) {
      toast({
        title: "Error",
        description: "Failed to generate plan. Please try again.",
        variant: "destructive",
      })
    } finally {
      setIsGeneratingPlan(false)
    }
  }

  const handleExecuteWorkflow = async () => {
    if (!workflowPlan || !activeThread || !activeMessage) return

    let finalPlan = workflowPlan

    if (isAdvancedMode && monacoEditorRef.current) {
      try {
        const editorContent = monacoEditorRef.current.getValue()
        finalPlan = JSON.parse(editorContent); // Parse the full workflow plan
      } catch (error) {
        toast({
          title: "Invalid JSON",
          description: "Please fix the JSON syntax errors before executing.",
          variant: "destructive",
        })
        return
      }
    }

    setIsExecuting(true)
    setExecutionLog([])

    try {
      // First, send the plan data to the backend
      await apiService('/execute/', {
        method: 'POST',
        body: JSON.stringify({
          thread_id: activeThread.id,
          message_id: activeMessage.id,
          workflow_plan: finalPlan
        }),
      });

      // Then open the EventSource for streaming logs
      const eventSource = new EventSource(
        `${API_BASE_URL}/execute/stream/?thread_id=${activeThread.id}&message_id=${activeMessage.id}`
      );

      eventSource.onmessage = (event) => {
          const data = JSON.parse(event.data);
          setExecutionLog((prev: any[]) => [...prev, data]);

          // Check for different types of completion messages
          if (data.type === 'result' || data.type === 'complete') {
              if (data.map_result) {
                  setMapResult(data.map_result);
              }
              eventSource.close();
              setIsExecuting(false);
              toast({
                  title: "Execution Complete",
                  description: "Workflow executed successfully. Check the map for results.",
              });
          }
      };

      eventSource.onerror = (err) => {
          console.error("EventSource failed:", err);
          eventSource.close();
          setIsExecuting(false);
          toast({
              title: "Execution Error", 
              description: "An error occurred during workflow execution.",
              variant: "destructive",
          });
      };
    } catch (error) {
      console.error('Execute workflow error:', error);
      setIsExecuting(false);
      toast({
        title: "Execution Error",
        description: "Failed to start workflow execution. Please try again.",
        variant: "destructive",
      });
    }
  }

  const handleUploadFile = async (formData: FormData) => {
    if (!activeThread) {
        toast({ title: "No Active Thread", description: "Please select or create an analysis thread first.", variant: "destructive" });
        return;
    }
    
    // Append thread ID to form data
    formData.append('thread_id', activeThread.id);

    try {
      const response = await fetch(`${API_BASE_URL}/upload/`, {
        method: 'POST',
        body: formData,
        // Don't set Content-Type header - let browser set it for multipart/form-data
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const responseData = await response.json();
      
      const newLayer: UserDataLayer = {
        id: responseData.layer_id,
        name: responseData.layer_name,
        data_type: formData.get('data_type') as "Vector" | "Raster",
        file_path: responseData.file_path,
        thread_id: activeThread.id,
      };

      setDataLayers((prev: UserDataLayer[]) => [...prev, newLayer])
      setUploadDialogOpen(false)

      toast({
        title: "Upload Successful",
        description: `${newLayer.name} has been uploaded successfully.`,
      })
    } catch (error) {
      console.error('Upload error:', error);
      toast({
        title: "Upload Failed",
        description: "Failed to upload file. Please try again.",
        variant: "destructive",
      })
    }
  }

  const getStatusIcon = (status: any) => {
    // Status logic needs to be derived from messages/results
    // This is a placeholder
    if (mapResult) return <CheckCircle className="h-4 w-4 text-green-500" />
    if (isExecuting) return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
    if (workflowPlan) return <FileText className="h-4 w-4 text-yellow-500" />
    return <FileText className="h-4 w-4 text-gray-500" />
  }

  const currentThreadLayers = dataLayers.filter((layer) => layer.thread_id === activeThread?.id)

  return (
// ... (The rest of the JSX remains largely the same, only minor changes to props)
    <div className="h-screen w-full flex flex-col">
      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden">
        <ResizablePanelGroup direction="horizontal" className="h-full">
          {/* Analysis History Panel */}
          <ResizablePanel defaultSize={20} minSize={15}>
            <Card className="h-full rounded-none border-r">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg">Analysis History</CardTitle>
                <Button onClick={handleNewAnalysis} className="w-full">
                  <Plus className="h-4 w-4 mr-2" />
                  New Analysis
                </Button>
              </CardHeader>
              <CardContent className="p-0">
                <ScrollArea className="h-[calc(100vh-200px)]">
                  <div className="space-y-2 p-4">
                    {threads.map((thread) => (
                      <div
                        key={thread.id}
                        className={`p-3 rounded-lg cursor-pointer transition-colors ${
                          activeThread?.id === thread.id
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted hover:bg-muted/80"
                        }`}
                        onClick={() => setActiveThread(thread)}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium text-sm truncate">{thread.title}</span>
                          {/* The status icon will now be dynamic based on state */}
                          {activeThread?.id === thread.id && getStatusIcon(null)}
                        </div>
                        <p className="text-xs opacity-70">{new Date(thread.created_at).toLocaleDateString()}</p>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </ResizablePanel>

          <ResizableHandle />

          {/* Map Viewer Panel (Center) */}
          <ResizablePanel defaultSize={50} minSize={30}>
            <Card className="h-full rounded-none border-r">
              <CardHeader>
                <CardTitle className="text-lg flex items-center">
                  <Map className="h-5 w-5 mr-2" />
                  Map Viewer
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0 h-[calc(100%-80px)]">
                <div className="h-full bg-muted flex items-center justify-center">
                  {mapResult ? (
                    <div className="text-center">
                      <div className="w-full h-64 bg-green-100 rounded mb-4 flex items-center justify-center">
                        <div className="text-center">
                          <Map className="h-12 w-12 mx-auto mb-2 text-green-600" />
                          <p className="font-medium">Analysis Result</p>
                          <p className="text-sm text-muted-foreground">Layer: {mapResult.name}</p>
                        </div>
                      </div>
                      <Badge variant="outline">Analysis Complete</Badge>
                    </div>
                  ) : (
                    <div className="text-center text-muted-foreground">
                      <Map className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No map results yet</p>
                      <p className="text-sm">Execute a workflow to see results</p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </ResizablePanel>

          <ResizableHandle />

          {/* Workflow & Logs Panel (Right) */}
          <ResizablePanel defaultSize={30} minSize={25}>
            <Card className="h-full rounded-none">
              <CardHeader>
                <CardTitle className="text-lg">Workflow & Logs</CardTitle>
              </CardHeader>
              <CardContent className="p-0 h-[calc(100%-80px)]">
                <Tabs defaultValue="workflow" className="h-full">
                  <TabsList className="grid w-full grid-cols-3">
                    <TabsTrigger value="workflow">Workflow Plan</TabsTrigger>
                    <TabsTrigger value="logs">Execution Log</TabsTrigger>
                    <TabsTrigger value="map">Map Results</TabsTrigger>
                  </TabsList>

                  <TabsContent value="workflow" className="h-[calc(100%-40px)] p-4">
                    {workflowPlan && workflowPlan.plan ? (
                      <div className="space-y-4 h-full">
                        <div className="flex items-center space-x-2">
                          <Switch id="advanced-mode" checked={isAdvancedMode} onCheckedChange={setIsAdvancedMode} />
                          <Label htmlFor="advanced-mode">Advanced Editing Mode</Label>
                        </div>

                        <div className="h-[calc(100%-100px)] overflow-hidden">
                          {isAdvancedMode ? (
                            <MonacoEditor
                              height="100%"
                              language="json"
                              theme="vs-dark"
                              value={JSON.stringify(workflowPlan, null, 2)}
                              onMount={(editor) => {
                                monacoEditorRef.current = editor
                              }}
                              options={{
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                fontSize: 12,
                              }}
                            />
                          ) : (
                            <ScrollArea className="h-full">
                              <div className="space-y-3">
                                <div className="p-3 bg-muted rounded">
                                  <h4 className="font-medium mb-2">Overall Reasoning</h4>
                                  <p className="text-sm">{workflowPlan.overall_reasoning || "No reasoning provided"}</p>
                                </div>

                                <Accordion type="single" collapsible className="w-full">
                                  {workflowPlan.plan && workflowPlan.plan.length > 0 ? (
                                    workflowPlan.plan.map((step, index) => (
                                      <AccordionItem key={`step-${index}`} value={`step-${index}`} className="border rounded-lg mb-2">
                                        <AccordionTrigger className="px-4 py-2 hover:bg-muted/50 rounded-t-lg">
                                          <div className="flex items-center gap-3 w-full">
                                            <div className="flex items-center gap-2">
                                              <Badge variant="outline" className="text-xs">{index + 1}</Badge>
                                              <span className="font-medium text-sm">{step.tool_name}</span>
                                            </div>
                                            <div className="text-xs text-muted-foreground truncate flex-1 text-left">
                                              {step.reasoning?.slice(0, 80)}...
                                            </div>
                                          </div>
                                        </AccordionTrigger>
                                        <AccordionContent className="px-4 pb-4 space-y-3">
                                          <div>
                                            <Label className="text-xs font-medium">Reasoning</Label>
                                            <p className="text-sm mt-1">{step.reasoning}</p>
                                          </div>
                                          <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                              <Label className="text-xs font-medium">Parameters (JSON)</Label>
                                              {jsonValidationErrors[`step-${index}`] ? (
                                                <div className="flex items-center gap-1">
                                                  <AlertCircle className="h-3 w-3 text-red-500" />
                                                  <span className="text-xs text-red-500">Invalid JSON</span>
                                                </div>
                                              ) : (
                                                <div className="flex items-center gap-1">
                                                  <CheckCircle className="h-3 w-3 text-green-500" />
                                                  <span className="text-xs text-green-500">Valid JSON</span>
                                                </div>
                                              )}
                                            </div>
                                            <div className="border rounded-md overflow-hidden">
                                              <MonacoEditor
                                                height="200px"
                                                language="json"
                                                theme="vs-dark"
                                                value={JSON.stringify(step.parameters || {}, null, 2)}
                                                onMount={(editor) => {
                                                  stepEditorsRef.current[`step-${index}`] = editor
                                                }}
                                                onChange={(value) => {
                                                  const stepKey = `step-${index}`
                                                  try {
                                                    const parsedParams = JSON.parse(value || '{}')
                                                    const newPlan = { ...workflowPlan }
                                                    if (newPlan.plan && newPlan.plan[index]) {
                                                      newPlan.plan[index].parameters = parsedParams
                                                      setWorkflowPlan(newPlan)
                                                    }
                                                    // Clear validation error
                                                    setJsonValidationErrors(prev => {
                                                      const newErrors = { ...prev }
                                                      delete newErrors[stepKey]
                                                      return newErrors
                                                    })
                                                  } catch (error) {
                                                    // Set validation error
                                                    setJsonValidationErrors(prev => ({
                                                      ...prev,
                                                      [stepKey]: (error as Error).message
                                                    }))
                                                  }
                                                }}
                                                options={{
                                                  minimap: { enabled: false },
                                                  scrollBeyondLastLine: false,
                                                  fontSize: 12,
                                                  wordWrap: "on",
                                                  lineNumbers: "on",
                                                  folding: true,
                                                  automaticLayout: true,
                                                }}
                                              />
                                            </div>
                                          </div>
                                        </AccordionContent>
                                      </AccordionItem>
                                    ))
                                  ) : (
                                    <div className="text-center text-muted-foreground p-4">
                                      <p className="text-sm">No workflow steps available</p>
                                    </div>
                                  )}
                                </Accordion>
                              </div>
                            </ScrollArea>
                          )}
                        </div>

                        <Button onClick={handleExecuteWorkflow} className="w-full" disabled={isExecuting || !workflowPlan || !workflowPlan.plan || workflowPlan.plan.length === 0}>
                          {isExecuting ? (
                            <>
                              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                              Executing...
                            </>
                          ) : (
                            <>
                              <Play className="h-4 w-4 mr-2" />
                              Execute Workflow
                            </>
                          )}
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-full text-muted-foreground">
                        <div className="text-center">
                          <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
                          <p>No workflow plan generated yet</p>
                          <p className="text-sm">Enter a query and click "Generate Plan"</p>
                        </div>
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="logs" className="h-[calc(100%-40px)] p-4">
                    <ScrollArea className="h-full">
                      <div className="space-y-2">
                        {executionLog.length > 0 ? (
                          executionLog.map((log: any, index: number) => (
                            <div key={index} className="text-xs font-mono p-2 bg-muted rounded">
                              <span className={`font-semibold ${
                                log.type === 'error' ? 'text-red-500' : 
                                log.type === 'complete' ? 'text-green-500' : 
                                'text-blue-500'
                              }`}>
                                [{log.type || 'log'}]
                              </span>
                              {' '}
                              {log.content || JSON.stringify(log)}
                            </div>
                          ))
                        ) : (
                          <div className="text-xs text-muted-foreground">No execution logs yet...</div>
                        )}
                      </div>
                    </ScrollArea>
                  </TabsContent>

                  <TabsContent value="map" className="h-[calc(100%-40px)] p-4">
                    <MapComponent 
                      mapResult={mapResult || undefined} 
                      isVisible={!!mapResult}
                    />
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      {/* Bottom Query Bar (ChatGPT-style) */}
      <div className="border-t bg-background p-4">
        <div className="max-w-4xl mx-auto space-y-3">
          <div className="flex items-end space-x-3">
            <div className="flex-1">
              <Textarea
                placeholder="Describe your geospatial analysis requirements..."
                value={userQuery}
                onChange={(e) => setUserQuery(e.target.value)}
                className="min-h-[60px] resize-none"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleGeneratePlan()
                  }
                }}
              />
            </div>
            <div className="flex space-x-2">
              <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="icon" disabled={!activeThread}>
                    <Upload className="h-4 w-4" />
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Upload Data Layer</DialogTitle>
                  </DialogHeader>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault()
                      const formData = new FormData(e.currentTarget)
                      handleUploadFile(formData)
                    }}
                    className="space-y-4"
                  >
                    <div className="space-y-2">
                      <Label htmlFor="name">Layer Name</Label>
                      <Input id="name" name="name" required />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="data_type">Data Type</Label>
                      <Select name="data_type" required>
                        <SelectTrigger>
                          <SelectValue placeholder="Select data type" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Vector">Vector</SelectItem>
                          <SelectItem value="Raster">Raster</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="file">File</Label>
                      <Input id="file" name="file" type="file" accept=".zip,.geojson,.tif,.tiff,.shp" required />
                      <p className="text-xs text-muted-foreground">
                        Upload GeoJSON, GeoTIFF, or a ZIP containing a Shapefile.
                      </p>
                    </div>
                    <Button type="submit" className="w-full">
                      Upload Layer
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
              <Button 
                onClick={handleGeneratePlan} 
                disabled={!userQuery.trim() || isGeneratingPlan || !activeThread}
                className="px-4"
              >
                {isGeneratingPlan ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Settings className="h-4 w-4 mr-2" />
                    Generate Plan
                  </>
                )}
              </Button>
            </div>
          </div>

          {/* Data Layers Toggle */}
          {currentThreadLayers.length > 0 && (
            <div className="flex items-center space-x-2">
              <Button variant="outline" size="sm" onClick={() => setShowDataLayers(!showDataLayers)}>
                <FileText className="h-4 w-4 mr-2" />
                Data Layers ({currentThreadLayers.length})
              </Button>
              {showDataLayers && (
                <div className="flex flex-wrap gap-2">
                  {currentThreadLayers.map((layer) => (
                    <Badge key={layer.id} variant="secondary" className="text-xs">
                      {layer.name} ({layer.data_type})
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
