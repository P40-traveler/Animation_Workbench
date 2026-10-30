export type Spec={canvas_width:number;canvas_height:number;pivot_x:number;pivot_y:number;body_width:number;body_height:number;target_frame_count:number;default_duration_ms:number;motion_description:string;prompt:string;locked_notes:string;reference_ids:string[];loop:boolean};
export type Frame={id:string;image_id:string;duration_ms:number;offset_x:number;offset_y:number};
export type Effect={id:string;name:string;image_ids:string[];durations_ms:number[];start_ms:number;x:number;y:number;opacity:number;z:'back'|'front';visible:boolean};
export type Revision={id:string;action_id:string;number:number;label:string;spec:Spec;frames:Frame[];effects:Effect[];events:{id:string;name:string;frame_id:string;offset_ms:number}[];review_status:string};
export type Action={id:string;asset_id:string;name:string;kind:string;current_revision_id:string};
export type Asset={id:string;name:string;description:string;references:{image_id:string;purpose:string;note:string}[]};
export type ImageInfo={id:string;url:string;width:number;height:number;filename:string;source:string};
export type Issue={id:string;revision_id:string;frame_id:string;layer_id:string;rect:Rect|null;category:string;message:string;status:string};
export type Task={id:string;action_id:string;status:string;kind:string;instruction:string;candidate_revision_id:string|null;base_revision_id:string};
export type Rect={x:number;y:number;width:number;height:number};
export type Workspace={project:{id:string;name:string};assets:Asset[];actions:Action[];revisions:Revision[];images:ImageInfo[];issues:Issue[];tasks:Task[]};
export async function api<T=any>(path:string,body?:unknown,method?:string):Promise<T>{const r=await fetch('/api'+path,{method:method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});if(!r.ok){let e;try{e=await r.json()}catch{throw Error(`HTTP ${r.status}`)}throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail||e));}return r.json()}
export const uid=()=>crypto.randomUUID();
export const clone=<T,>(v:T):T=>structuredClone(v);
