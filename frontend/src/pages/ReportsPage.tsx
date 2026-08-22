import { Download, Eye } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';

export function ReportsPage(){
  const [rows,setRows]=useState<any[]|null>(null);
  useEffect(()=>{api.get('/reports').then(response=>setRows(response.data)).catch(()=>setRows([]))},[]);
  return <><div className="page-head"><div><h1>Reports</h1><p>Evidence-backed exports from completed sessions</p></div></div>
    <section className="table-card">{rows===null?<div className="state">Loading reports…</div>:rows.length===0?<div className="empty">No completed sessions available.</div>:<table><thead><tr><th>Session</th><th>Attendance</th><th>Engagement</th><th>Attention</th><th>Fatigue</th><th>Actions</th></tr></thead><tbody>{rows.map(row=><tr key={row.session_id}><td>{row.name}<small>{new Date(row.created_at).toLocaleString()} · {row.analytics_mode}</small></td><td>{row.average_attendance}%</td><td>{row.average_engagement}%</td><td>{row.average_attention}%</td><td>{row.average_fatigue}%</td><td className="actions"><Link to={`/sessions/${row.session_id}`}><Eye size={15}/>View</Link><a href={`/api/sessions/${row.session_id}/report?format=pdf`}><Download size={15}/>PDF</a><a href={`/api/sessions/${row.session_id}/report?format=csv`}><Download size={15}/>CSV</a></td></tr>)}</tbody></table>}</section></>
}
