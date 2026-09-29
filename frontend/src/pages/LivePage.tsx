/* eslint-disable react-hooks/refs -- stream activity is read only for the live pipeline status indicator */
import{Camera,CheckCircle2,Circle,Loader2,Radio,Square,XCircle}from'lucide-react';import{useCallback,useEffect,useRef,useState}from'react';import{MetricValue}from'../components/MetricValue';import{useToast}from'../components/Toast';import{api}from'../services/api';import type{MetricAvailability,Session}from'../types';
const wsUrl=(path:string)=>{const token=localStorage.getItem('ambisense_token');return `${location.protocol==='https:'?'wss':'ws'}://${location.hostname}:8000${path}${token?`?access_token=${encodeURIComponent(token)}`:''}`};
function cameraError(error:any){switch(error?.name){case'NotAllowedError':return'Camera permission was denied. Open the camera icon in your browser address bar, allow camera access for localhost, then try again.';case'NotFoundError':return'No camera was detected. Connect a webcam and reload the page.';case'NotReadableError':return'The camera could not be opened. Close Teams, Zoom, Camera, or another application using it, then try again.';case'OverconstrainedError':return'The selected camera cannot provide the requested video format. Choose another camera.';case'SecurityError':return'Camera access requires a secure localhost or HTTPS page.';default:return error?.message||'The camera could not be started.'}}
const ACTIVITY_CONTEXTS=['LECTURE','EXAMINATION','GROUP_DISCUSSION','LABORATORY','STUDENT_PRESENTATION','INDEPENDENT_WRITING','READING','VIDEO_SCREENING','BREAK'];
const METRIC_ROWS:Array<[string,string,'percent'|'count',string|undefined]>=[
 ['occupancy','Anonymous occupancy estimate','count','people'],
 ['peak_occupancy','Peak anonymous occupancy','count','people'],
 ['unoccupied_capacity','Estimated unoccupied capacity','count','seats'],
 ['visual_orientation','Visual-orientation estimate','percent',undefined],
 ['observable_participation','Observable participation indicator','percent',undefined],
 ['prolonged_eye_closure','Possible prolonged eye closure','count','events'],
 ['possible_fatigue','Possible fatigue indicator','percent',undefined],
 ['yawning','Yawning observations','count','events'],
 ['raised_hands','Raised-hand observations','count','events'],
 ['frame_quality','Frame-quality score','percent',undefined],
];
function PipelineStep({label,state}:{label:string;state:'waiting'|'active'|'healthy'|'warning'|'failed'}){
 const icon={waiting:<Circle size={15}/>,active:<Loader2 size={15} className="spin"/>,healthy:<CheckCircle2 size={15}/>,warning:<XCircle size={15}/>,failed:<XCircle size={15}/>}[state];
 const tone={waiting:'neutral',active:'info',healthy:'success',warning:'warning',failed:'danger'}[state];
 return <article><span className={`badge badge-${tone}`}>{icon}{label}</span></article>;
}
export function LivePage(){const{show}=useToast();const[sessions,setSessions]=useState<Session[]>([]),[selected,setSelected]=useState(''),[devices,setDevices]=useState<MediaDeviceInfo[]>([]),[deviceId,setDeviceId]=useState(''),[classrooms,setClassrooms]=useState<any[]>([]),[classroomId,setClassroomId]=useState(''),[activityContext,setActivityContext]=useState('LECTURE'),[live,setLive]=useState<any>(null),[events,setEvents]=useState<any[]>([]),[running,setRunning]=useState(false),[starting,setStarting]=useState(false),[requestingPermission,setRequestingPermission]=useState(false),[error,setError]=useState(''),[connection,setConnection]=useState('DISCONNECTED'),[health,setHealth]=useState<any>(null),[framesSent,setFramesSent]=useState(0),[elapsedSeconds,setElapsedSeconds]=useState(0);const videoRef=useRef<HTMLVideoElement>(null),canvasRef=useRef<HTMLCanvasElement>(null),liveSocketRef=useRef<WebSocket|null>(null),monitorSocketRef=useRef<WebSocket|null>(null),timerRef=useRef<number|null>(null),heartbeatRef=useRef<number|null>(null),streamRef=useRef<MediaStream|null>(null),retryRef=useRef(0),lastSequence=useRef(0),closedRef=useRef(false),mountedRef=useRef(true),awaitingAckRef=useRef(false),startupTimeoutRef=useRef<number|null>(null),sessionStartedAt=useRef<number|null>(null);
useEffect(()=>{if(!running)return;const id=window.setInterval(()=>{if(sessionStartedAt.current)setElapsedSeconds(Math.round((Date.now()-sessionStartedAt.current)/1000))},1000);return()=>window.clearInterval(id)},[running]);
const refreshSessions=useCallback(()=>api.get('/sessions').then(r=>setSessions(r.data)),[]);useEffect(()=>{mountedRef.current=true;void refreshSessions();api.get('/v1/classrooms').then(r=>setClassrooms(Array.isArray(r.data)?r.data:[])).catch(()=>{});navigator.mediaDevices?.enumerateDevices().then(rows=>setDevices(rows.filter(row=>row.kind==='videoinput'))).catch(()=>{});return()=>{mountedRef.current=false;if(timerRef.current)clearInterval(timerRef.current);if(heartbeatRef.current)clearInterval(heartbeatRef.current);if(startupTimeoutRef.current)clearTimeout(startupTimeoutRef.current);const socket=liveSocketRef.current;if(socket?.readyState===WebSocket.OPEN)socket.send('STOP');socket?.close();monitorSocketRef.current?.close();streamRef.current?.getTracks().forEach(track=>track.stop())}},[refreshSessions]);useEffect(()=>{if(selected)api.get('/v1/system/pipeline-health',{params:{session_id:selected}}).then(r=>setHealth(r.data)).catch(()=>{})},[selected,live]);
const connectMonitor=useCallback((id:string)=>{if(!id||running||starting)return;closedRef.current=false;const connect=()=>{if(closedRef.current)return;setConnection(retryRef.current?'RECONNECTING':'CONNECTING');const socket=new WebSocket(wsUrl(`/ws/sessions/${id}`));monitorSocketRef.current=socket;socket.onopen=()=>{retryRef.current=0;setConnection('CONNECTED')};socket.onmessage=e=>{const data=JSON.parse(e.data);if(data.sequence&&data.sequence<=lastSequence.current)return;lastSequence.current=data.sequence||lastSequence.current;setLive(data);if(data.analytics)setEvents(old=>[data.analytics,...old].slice(0,20))};socket.onclose=()=>{if(closedRef.current)return;setConnection('RECONNECTING');window.setTimeout(connect,Math.min(30000,1000*2**retryRef.current++))};socket.onerror=()=>socket.close()};connect();return()=>{closedRef.current=true;monitorSocketRef.current?.close();monitorSocketRef.current=null}},[running,starting]);useEffect(()=>{if(!selected||running||starting)return;return connectMonitor(selected)},[selected,running,starting,connectMonitor]);
async function updateDevices(){const rows=await navigator.mediaDevices.enumerateDevices();const cameras=rows.filter(row=>row.kind==='videoinput');setDevices(cameras);if(!deviceId&&cameras[0])setDeviceId(cameras[0].deviceId)}
function cancelStart(){setStarting(false);setRequestingPermission(false);if(startupTimeoutRef.current){window.clearTimeout(startupTimeoutRef.current);startupTimeoutRef.current=null}liveSocketRef.current?.close();liveSocketRef.current=null;streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;if(videoRef.current)videoRef.current.srcObject=null;setConnection('DISCONNECTED');show('Session start cancelled.','info')}
async function startCamera(){
 if(!navigator.mediaDevices?.getUserMedia){setError('This browser does not support camera capture. Use a current Chrome, Edge, or Firefox on localhost or HTTPS.');return}
 setStarting(true);setRequestingPermission(true);setRunning(false);setError('');setLive(null);setEvents([]);setFramesSent(0);setElapsedSeconds(0);sessionStartedAt.current=null;lastSequence.current=0;awaitingAckRef.current=false
 try{
  console.info('[CAMERA] Requesting camera permission');const stream=await navigator.mediaDevices.getUserMedia({video:{deviceId:deviceId?{exact:deviceId}:undefined,width:{ideal:1280},height:{ideal:720},frameRate:{ideal:15,max:30}},audio:false});
  setRequestingPermission(false);console.info('[CAMERA] Camera permission granted');streamRef.current=stream;await updateDevices();const video=videoRef.current;if(!video)throw new Error('Camera preview element is unavailable.');video.srcObject=stream;await video.play();
  if(!video.videoWidth)await new Promise<void>((resolve,reject)=>{const timeout=window.setTimeout(()=>reject(new Error('The camera opened but did not produce video frames.')),10000);video.onloadedmetadata=()=>{window.clearTimeout(timeout);resolve()}});
  console.info('[CAMERA] Video stream started',video.videoWidth,video.videoHeight);setConnection('CONNECTING_BACKEND');const created=await api.post('/sessions',{name:`Live classroom ${new Date().toLocaleString()}`,source_type:'LIVE',classroom_id:classroomId?Number(classroomId):undefined,activity_context:activityContext}),id=String(created.data.id);setSelected(id);setSessions(old=>[created.data,...old]);
  const socket=new WebSocket(wsUrl(`/ws/live/${id}`));liveSocketRef.current=socket;
  startupTimeoutRef.current=window.setTimeout(()=>{if(!running){setError('Backend is not acknowledging camera frames. Check model loading and backend logs.');socket.close()}},45000);
  socket.onopen=()=>{if(!mountedRef.current)return;console.info('[API] Live WebSocket connected');setConnection('CONNECTED');sendFrame(socket);timerRef.current=window.setInterval(()=>sendFrame(socket),333);heartbeatRef.current=window.setInterval(()=>{if(socket.readyState===WebSocket.OPEN)socket.send('PING')},10000)};
  socket.onmessage=e=>{const data=JSON.parse(e.data);if(data.type==='pong')return;if(data.error){awaitingAckRef.current=false;setError(`${data.error}${data.reference?` (reference ${data.reference})`:''}`);return}if(data.type==='status'){setConnection(data.stage);return}if(data.type!=='live_metrics')return;awaitingAckRef.current=false;if(startupTimeoutRef.current)clearTimeout(startupTimeoutRef.current);if(data.sequence&&data.sequence<=lastSequence.current)return;lastSequence.current=data.sequence||0;if(!running){setRunning(true);sessionStartedAt.current=Date.now();show('Live session started.','success')}setStarting(false);setConnection('CONNECTED');setLive({analytics:data,stage:'PROCESSING',processing_speed:data.transport?.fps,latency_ms:data.transport?.latency_ms});setEvents(old=>[data,...old].slice(0,20))};
  socket.onerror=()=>setError('WebSocket connection failed. Confirm the FastAPI backend is running on localhost:8000.');socket.onclose=()=>{awaitingAckRef.current=false;if(timerRef.current)clearInterval(timerRef.current);if(heartbeatRef.current)clearInterval(heartbeatRef.current);timerRef.current=null;heartbeatRef.current=null;if(mountedRef.current){setRunning(false);setStarting(false);setConnection('DISCONNECTED');void refreshSessions()}}
 }catch(e:any){console.error('[CAMERA] Startup failed',e);streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;if(videoRef.current)videoRef.current.srcObject=null;setError(cameraError(e));setStarting(false);setRequestingPermission(false);setConnection('DISCONNECTED')}
}
function sendFrame(socket:WebSocket){const video=videoRef.current,canvas=canvasRef.current;if(awaitingAckRef.current||!video||!canvas||socket.readyState!==WebSocket.OPEN||video.readyState<2||!video.videoWidth)return;const width=Math.min(960,video.videoWidth),scale=width/video.videoWidth;canvas.width=width;canvas.height=Math.round(video.videoHeight*scale);const context=canvas.getContext('2d');if(!context)return;context.drawImage(video,0,0,canvas.width,canvas.height);canvas.toBlob(blob=>blob?.arrayBuffer().then(buffer=>{if(socket.readyState===WebSocket.OPEN){awaitingAckRef.current=true;socket.send(buffer);setFramesSent(value=>{const next=value+1;if(next===1||next%20===0)console.info('[CAMERA] Frames captured and sent',next);return next})}}),'image/jpeg',.72)}
async function stop(){setConnection('FINALIZING');if(timerRef.current)clearInterval(timerRef.current);if(heartbeatRef.current)clearInterval(heartbeatRef.current);timerRef.current=null;heartbeatRef.current=null;const socket=liveSocketRef.current;if(socket?.readyState===WebSocket.OPEN){console.info('[SESSION] Requesting live processing completion');socket.send('STOP')}else socket?.close();streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;if(videoRef.current)videoRef.current.srcObject=null;show('Session stopped. Finalizing evidence…','info')}
const a=live?.analytics;const pipeline=a?.pipeline||{};
const stages:Array<[string,'waiting'|'active'|'healthy'|'warning'|'failed']>=[
 ['Camera connected',streamRef.current?.active?'healthy':starting?'active':'waiting'],
 ['Frames transmitting',framesSent>0?'healthy':starting?'active':'waiting'],
 ['Backend receiving',pipeline.backend_receiving?'healthy':(health?.backend_receiving_frames?'healthy':running?'warning':'waiting')],
 ['Models loaded',pipeline.models_loaded||health?.yolo_model_state==='ENABLED'?'healthy':starting?'active':'waiting'],
 ['Inference running',pipeline.inference_running?'healthy':running?'warning':'waiting'],
 ['Metrics aggregating',pipeline.metrics_aggregating?'healthy':running?'warning':'waiting'],
 ['Live updates connected',pipeline.live_updates_connected||connection==='CONNECTED'?'healthy':connection==='RECONNECTING'?'warning':'waiting'],
];
const connectionLabel:Record<string,string>={DISCONNECTED:'Idle',CONNECTING:'Connecting to backend…',RECONNECTING:'Reconnecting…',CONNECTED:'Connected',LOADING_MODELS:'Initializing models…',CAPTURING_LIVE_CAMERA:'Running',FINALIZING:'Stopping session…',CONNECTING_BACKEND:'Connecting to backend…'};
const primaryLabel=requestingPermission?'Requesting camera permission…':starting?connectionLabel[connection]||'Starting…':'Start webcam analysis';
return <>
<div className="page-head"><div><h1>Live classroom</h1><p>Anonymous, real-time observable classroom signals</p></div><span className="live-dot">● {connectionLabel[connection]||connection}</span></div>
<div className="notice">AmbiSense uses anonymous session-local tracking. It does not identify students, and occupancy is not verified attendance. <details style={{display:'inline'}}><summary style={{display:'inline',cursor:'pointer'}}>Limitations</summary> Estimates can be affected by camera angle, lighting, occlusion, glasses, masks, and classroom activity, and must not be the sole basis for grading, discipline, or attendance decisions.</details></div>
<div className="live-controls">
 <select aria-label="Camera device" value={deviceId} disabled={running||starting} onChange={e=>setDeviceId(e.target.value)}><option value="">Default camera</option>{devices.map((row,index)=><option value={row.deviceId} key={row.deviceId}>{row.label||`Camera ${index+1}`}</option>)}</select>
 <select aria-label="Classroom" value={classroomId} disabled={running||starting} onChange={e=>setClassroomId(e.target.value)}><option value="">Unassigned classroom</option>{classrooms.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select>
 <select aria-label="Activity context" value={activityContext} disabled={running||starting} onChange={e=>setActivityContext(e.target.value)}>{ACTIVITY_CONTEXTS.map(v=><option key={v} value={v}>{v.replace(/_/g,' ')}</option>)}</select>
 <select aria-label="Live session" value={selected} disabled={running||starting} onChange={e=>{lastSequence.current=0;setSelected(e.target.value)}}><option value="">Select a prior session</option>{sessions.map(row=><option value={row.id} key={row.id}>{row.name} · {row.status}</option>)}</select>
 {running?<button onClick={()=>void stop()}><Square size={17}/>Stop camera</button>:starting?<button type="button" onClick={cancelStart}><Square size={17}/>Cancel</button>:<button onClick={()=>void startCamera()}><Camera size={17}/>{primaryLabel}</button>}
</div>
{error&&<div className="notice error" role="alert">{error}</div>}
<section className="model-health"><h2>Pipeline health</h2><div>{stages.map(([label,state])=><PipelineStep key={label} label={label} state={state}/>)}</div></section>
<div className="live-layout">
 <section className="video-panel">
  <video ref={videoRef} autoPlay muted playsInline controls={!running&&!starting} src={!running&&!starting&&selected?`/api/sessions/${selected}/video?annotated=true`:undefined}/>
  {running&&a?.annotated_image&&<img className="live-overlay" alt="Privacy-safe anonymous overlay" src={`data:image/jpeg;base64,${a.annotated_image}`}/>}
  <canvas ref={canvasRef} hidden/>
  {!selected&&!running&&!starting&&<div className="video-empty"><Radio size={38}/><b>Start a live session</b><span>The physical camera is processed in real time. Raw face crops are never stored.</span></div>}
 </section>
 <section className="live-metrics">
  {METRIC_ROWS.map(([key,label,kind,noun])=>{const contract:MetricAvailability|undefined=a?.metrics?.[key];return <MetricValue key={key} metric={contract} kind={kind} noun={noun} label={label}/>})}
  <div className="progress"><span>{running?`${String(Math.floor(elapsedSeconds/60)).padStart(2,'0')}:${String(elapsedSeconds%60).padStart(2,'0')} · `:''}{running?'Running':connectionLabel[connection]||connection} · {a?.transport?.fps??live?.processing_speed??0} FPS · {a?.transport?.latency_ms==null?'Latency unavailable':`${a.transport.latency_ms}ms`} · {framesSent} sent / {a?.transport?.frames_received??0} received / {a?.transport?.frames_processed??0} processed</span></div>
 </section>
</div>
<section className="table-card">
 <h2>Evidence quality</h2>
 {(()=>{const fq:MetricAvailability|undefined=a?.metrics?.frame_quality;if(!fq)return <div className="empty">No frame-quality evidence yet.</div>;
  const tips:string[]=[];if(!fq.available){if(fq.reason==='low_light')tips.push('Increase room lighting.');if(fq.reason==='excessive_blur')tips.push('Keep the camera stable.');if(fq.reason==='no_person_detected')tips.push('No person is detected. Move into frame.');if(fq.reason==='facial_landmarks_unavailable')tips.push('Face landmarks are not currently visible. Move closer to the camera.');if(fq.reason==='poor_frame_quality')tips.push('Move closer to the camera and improve lighting.')}
  return <>
   <MetricValue metric={fq} kind="percent" label="Frame quality"/>
   {tips.length>0&&<ul>{tips.map(t=><li key={t}>{t}</li>)}</ul>}
  </>})()}
</section>
<section className="table-card timeline"><h2>Live timeline</h2>{events.length?events.map((row,index)=><p key={index}><time>{new Date(row.timestamp).toLocaleTimeString()}</time> Occupancy {row.student_count} · Raised hands {row.raised_hands??0}</p>):<div className="empty">Live observations will appear after the backend processes the first camera frame.</div>}</section>
</>}
