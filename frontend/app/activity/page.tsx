"use client";
import {useEffect,useState} from "react";
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
type Event={agent:string;timestamp:string;output:unknown};
export default function Activity(){const [events,setEvents]=useState<Event[]>([]);useEffect(()=>{const id=localStorage.getItem("goalforge.activeGoalId");if(id)fetch(`${API}/goal/${id}`).then(r=>r.json()).then(g=>setEvents(g.agentLog||[]))},[]);return <main className="shell"><a className="pill" href="/">← Dashboard</a><h1 className="text-3xl font-black mt-6">Agent Activity</h1><p className="intro">Structured outputs from the specialist agents for the active goal.</p><div className="stack mt-6">{events.map((e,i)=><details className="card agent" key={i}><summary><b>{e.agent}</b> · {new Date(e.timestamp).toLocaleString()}</summary><pre className="json mt-3">{JSON.stringify(e.output,null,2)}</pre></details>)}</div></main>}
