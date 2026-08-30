// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../services/api';
import { LivePage } from './LivePage';
vi.mock('../services/api',()=>({api:{get:vi.fn(),post:vi.fn()}}));
class FakeSocket{
 static OPEN=1;readyState=1;bufferedAmount=0;onopen:any;onmessage:any;onerror:any;onclose:any;
 constructor(){setTimeout(()=>this.onopen?.(),0)}
 send(value:any){if(typeof value==='string')return;setTimeout(()=>this.onmessage?.({data:JSON.stringify({type:'live_metrics',sequence:1,timestamp:new Date().toISOString(),pipeline:{backend_receiving:true,models_loaded:true,inference_running:true,metrics_aggregating:true,live_updates_connected:true},transport:{fps:3,latency_ms:20,frames_received:1,frames_processed:1},metrics:{occupancy:{value:0,available:true}},student_count:0,raised_hands:0})}),0)}
 close(){this.readyState=3;this.onclose?.()}
}
beforeEach(()=>{vi.mocked(api.get).mockImplementation(async(url:any)=>({data:String(url).includes('pipeline-health')?{yolo_model_state:'ENABLED'}:[]} as any));vi.mocked(api.post).mockResolvedValue({data:{id:999,name:'Live test',status:'CREATED',source_type:'LIVE'}} as any);Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{enumerateDevices:vi.fn().mockResolvedValue([{kind:'videoinput',deviceId:'camera-1',label:'Camera'}]),getUserMedia:vi.fn().mockResolvedValue({active:true,getTracks:()=>[{stop:vi.fn()}]})}});vi.stubGlobal('WebSocket',FakeSocket as any);vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue();Object.defineProperty(HTMLVideoElement.prototype,'videoWidth',{configurable:true,get:()=>640});Object.defineProperty(HTMLVideoElement.prototype,'videoHeight',{configurable:true,get:()=>360});Object.defineProperty(HTMLMediaElement.prototype,'readyState',{configurable:true,get:()=>4});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as any);vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation((callback:any)=>callback(new Blob(['frame'])))});
afterEach(()=>vi.restoreAllMocks());
it('survives StrictMode, waits for a backend acknowledgement, and shows genuine zero occupancy',async()=>{render(<StrictMode><LivePage/></StrictMode>);fireEvent.click(await screen.findByText('Start webcam analysis'));expect(screen.getByText('Starting camera…')).toBeTruthy();expect(await screen.findByText('Stop camera')).toBeTruthy();expect((await screen.findAllByText('0')).length).toBeGreaterThan(0);await waitFor(()=>expect(screen.getByText(/sent \/ 1 received \/ 1 processed/)).toBeTruthy());fireEvent.click(screen.getByText('Stop camera'))});
