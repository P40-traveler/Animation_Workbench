import {useEffect,useRef,useState} from 'react';
export type DialogRequest={title:string;kind:'text'|'confirm';resolve:(value:string|null)=>void};
export default function AppDialog({request,onClose}:{request:DialogRequest;onClose:(value:string|null)=>void}){
  const ref=useRef<HTMLDialogElement>(null),input=useRef<HTMLInputElement>(null);const [value,setValue]=useState('');
  useEffect(()=>{ref.current?.showModal();if(request.kind==='text')input.current?.focus();else ref.current?.querySelector<HTMLButtonElement>('button[type=submit]')?.focus();return()=>ref.current?.close()},[]);
  return <dialog ref={ref} className="app-dialog" aria-labelledby="dialog-title" onCancel={e=>{e.preventDefault();onClose(null)}}><form onSubmit={e=>{e.preventDefault();if(request.kind==='confirm'||value.trim())onClose(request.kind==='confirm'?'yes':value.trim())}}><h2 id="dialog-title">{request.title}</h2>{request.kind==='text'?<label>名称<input ref={input} autoComplete="off" maxLength={200} value={value} onChange={e=>setValue(e.target.value)} required/></label>:<p>未保存的修改不会保留。</p>}<div className="button-row"><button type="button" onClick={()=>onClose(null)}>取消</button><button type="submit" className="primary" disabled={request.kind==='text'&&!value.trim()}>确认</button></div></form></dialog>
}
