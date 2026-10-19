"use client";
import {useEffect,useState} from "react";
import {subscribeWorkspace} from "@/lib/api/workspace";
import {applyWorkspaceEvent,emptyWorkspace} from "@/lib/data/workflow";

export function useWorkspace(){
  const [state,setState]=useState(emptyWorkspace);
  const [error,setError]=useState<string|null>(null);
  useEffect(()=>subscribeWorkspace(event=>setState(current=>applyWorkspaceEvent(current,event)),setError),[]);
  return {...state,error,setError};
}
