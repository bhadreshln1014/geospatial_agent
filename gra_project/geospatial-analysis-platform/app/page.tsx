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
import { Plus, Upload, Play, FileText, Map, Settings, Loader2, CheckCircle, AlertCircle, MapPin } from "lucide-react"
import { useToast } from "@/hooks/use-toast"
import dynamic from "next/dynamic"
import { apiService, API_BASE_URL } from "@/lib/api"

// Dynamically import Monaco Editor to avoid SSR issues
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false })

// Dynamically import Map Component to avoid SSR issues
const MapComponent = dynamic(() => import("@/components/map-component"), { ssr: false })

// Dynamically import the new ROI map component
const RoiMap = dynamic(() => import("@/components/RoiMap"), { ssr: false });


// --- API-aligned types ---
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
    execution_log?: any[];
    final_map_result?: MapResult;
    timestamp: string;
}


interface UserDataLayer {
  id: string
  name: string
  data_type: "Vector" | "Raster"
  file_path: string
  thread_id: string
}

interface WorkflowStep {
  step: number
  tool_name: string
  reasoning: string
  parameters: Record<string, any>
}

interface AgentWorkflowPlan {
  overall_reasoning: string
  plan: WorkflowStep[]
}

interface MapResult {
  url?: string | null;      // No longer used for vector, optional for raster
  type: 'vector' | 'raster';
  bbox: [number, number, number, number] | null;
  name: string;
  data?: any;               // For GeoJSON data
  service_type?: 'WMS';     // To identify GeoServer layers
  geoserver_url?: string;
  layer_name?: string;
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
  const [roi, setRoi] = useState<any | null>(null);
  const [roiDialogOpen, setRoiDialogOpen] = useState(false);


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
          const messages = await apiService<ThreadMessage[]>(`/threads/${activeThread.id}/messages/`);
          const lastMessage = messages[messages.length - 1];
          
          if (lastMessage) {
            setActiveMessage(lastMessage);
            setUserQuery(lastMessage.user_query || "");
            setWorkflowPlan(lastMessage.agent_workflow_plan || null);
            setExecutionLog(lastMessage.execution_log || []);
            setMapResult(lastMessage.final_map_result || null);
            setJsonValidationErrors({});
          } else {
            setActiveMessage(null);
            setUserQuery("");
            setWorkflowPlan(null);
            setExecutionLog([]);
            setMapResult(null);
            setJsonValidationErrors({});
          }

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
        setUserQuery("");
        setWorkflowPlan(null);
        setMapResult(null);
        setExecutionLog([]);
        setDataLayers([]);
        setActiveMessage(null);
        setRoi(null);
    } catch (error) {
        toast({ title: "Error", description: "Failed to create a new analysis thread.", variant: "destructive" });
    }
  }

  const handleRoiSelected = (roiGeoJson: any) => {
    setRoi(roiGeoJson);
    setRoiDialogOpen(false);
    toast({
      title: "Region of Interest Set",
      description: `ROI area has been captured successfully.`,
    });
  };

  const handleGeneratePlan = async () => {
    if (!userQuery.trim() || !activeThread) return

    setIsGeneratingPlan(true)
    try {
      const requestBody = {
        thread_id: activeThread.id,
        query: userQuery,
        roi: roi,
      };

      const planData = await apiService<ThreadMessage>('/plan/', {
        method: 'POST',
        body: JSON.stringify(requestBody),
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
        finalPlan = JSON.parse(editorContent);
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
      await apiService('/execute/', {
        method: 'POST',
        body: JSON.stringify({
          thread_id: activeThread.id,
          message_id: activeMessage.id,
          workflow_plan: finalPlan
        }),
      });

      const eventSource = new EventSource(
        `${API_BASE_URL}/execute/stream/?thread_id=${activeThread.id}&message_id=${activeMessage.id}`
      );

      eventSource.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    setExecutionLog((prev: any[]) => [...prev, data]);

    // Check for the completion message
    if (data.type === 'complete') {
        // If the workflow produced any kind of map result, set it.
        // The ClientSideMap component will handle the rendering logic.
        if (data.map_result) {
            setMapResult(data.map_result);
        }
        
        eventSource.close();
        setIsExecuting(false);
        toast({
            title: "Execution Complete",
            description: "Workflow finished successfully.",
        });
    }
};

      eventSource.onerror = (err) => {
          eventSource.close();
          setIsExecuting(false);
          toast({
              title: "Execution Error", 
              description: "An error occurred during workflow execution.",
              variant: "destructive",
          });
      };
    } catch (error) {
      setIsExecuting(false);
      toast({
        title: "Execution Error",
        description: "Failed to start workflow execution.",
        variant: "destructive",
      });
    }
  }

  const handleUploadFile = async (formData: FormData) => {
    if (!activeThread) {
        toast({ title: "No Active Thread", description: "Please select or create an analysis thread first.", variant: "destructive" });
        return;
    }
    
    formData.append('thread_id', activeThread.id);

    try {
      const response = await fetch(`${API_BASE_URL}/upload/`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

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
        description: `${newLayer.name} has been uploaded.`,
      })
    } catch (error) {
      toast({
        title: "Upload Failed",
        description: "Failed to upload file.",
        variant: "destructive",
      })
    }
  }

  const getStatusIcon = (status: any) => {
    if (mapResult) return <CheckCircle className="h-4 w-4 text-green-500" />
    if (isExecuting) return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
    if (workflowPlan) return <FileText className="h-4 w-4 text-yellow-500" />
    return <FileText className="h-4 w-4 text-gray-500" />
  }

  const currentThreadLayers = dataLayers.filter((layer) => layer.thread_id === activeThread?.id)

  return (
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
            <MapComponent 
              mapResult={mapResult || undefined} 
              isVisible={true}
            />
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
                              onMount={(editor) => { monacoEditorRef.current = editor }}
                              options={{ minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 12 }}
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
                                              {jsonValidationErrors[`step-${index}`] && (
                                                <div className="flex items-center gap-1">
                                                  <AlertCircle className="h-3 w-3 text-red-500" />
                                                  <span className="text-xs text-red-500">Invalid JSON</span>
                                                </div>
                                              )}
                                            </div>
                                            <div className="border rounded-md overflow-hidden">
                                              <MonacoEditor
                                                height="200px"
                                                language="json"
                                                theme="vs-dark"
                                                value={JSON.stringify(step.parameters || {}, null, 2)}
                                                onMount={(editor) => { stepEditorsRef.current[`step-${index}`] = editor }}
                                                onChange={(value) => {
                                                  const stepKey = `step-${index}`
                                                  try {
                                                    const parsedParams = JSON.parse(value || '{}')
                                                    const newPlan = { ...workflowPlan }
                                                    if (newPlan.plan && newPlan.plan[index]) {
                                                      newPlan.plan[index].parameters = parsedParams
                                                      setWorkflowPlan(newPlan)
                                                    }
                                                    setJsonValidationErrors(prev => {
                                                      const newErrors = { ...prev };
                                                      delete newErrors[stepKey];
                                                      return newErrors
                                                    })
                                                  } catch (error) {
                                                    setJsonValidationErrors(prev => ({ ...prev, [stepKey]: (error as Error).message }))
                                                  }
                                                }}
                                                options={{ minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 12, wordWrap: "on" }}
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
                            <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Executing...</>
                          ) : (
                            <><Play className="h-4 w-4 mr-2" /> Execute Workflow</>
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
                    <div className="text-center text-muted-foreground">
                      <p className="text-sm">Map is displayed in the main viewer panel</p>
                      {mapResult && (
                        <div className="mt-4 p-4 bg-muted rounded-lg">
                          <h4 className="font-medium">Map Details</h4>
                          <div className="text-sm space-y-1">
                            <p><span className="font-medium">Name:</span> {mapResult.name}</p>
                            <p><span className="font-medium">Type:</span> {mapResult.type}</p>
                            <p><span className="font-medium">URL:</span> {mapResult.url || 'In-memory data'}</p>
                            {mapResult.bbox && (
                              <p><span className="font-medium">Bounds:</span> [{mapResult.bbox.join(', ')}]</p>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
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
                      <Input id="file" name="file" type="file" accept=".zip,.geojson,.tif,.tiff,.shp,.gpkg" required />
                      <p className="text-xs text-muted-foreground">
                        Upload GeoJSON, GeoTIFF, GPKG, or a ZIP containing a Shapefile.
                      </p>
                    </div>
                    <Button type="submit" className="w-full">
                      Upload Layer
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>

              <Dialog open={roiDialogOpen} onOpenChange={setRoiDialogOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="icon" title="Select Region of Interest">
                    <MapPin className={`h-4 w-4 ${roi ? 'text-green-500' : ''}`} />
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-4xl">
                  <DialogHeader>
                    <DialogTitle>Select Region of Interest</DialogTitle>
                  </DialogHeader>
                  <p className="text-sm text-muted-foreground">
                    Draw a polygon on the map to define your area of analysis.
                  </p>
                  <RoiMap onRoiSelected={handleRoiSelected} />
                </DialogContent>
              </Dialog>

              <Button 
                onClick={handleGeneratePlan} 
                disabled={!userQuery.trim() || isGeneratingPlan || !activeThread}
                className="px-4"
              >
                {isGeneratingPlan ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Generating...</>
                ) : (
                  <><Settings className="h-4 w-4 mr-2" /> Generate Plan</>
                )}
              </Button>
            </div>
          </div>

          {roi && (
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-green-500" />
              <span>A custom polygon ROI is active.</span>
              <Button variant="link" size="sm" className="ml-2 h-auto p-0 text-red-500" onClick={() => setRoi(null)}>
                Clear
              </Button>
            </div>
          )}

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
