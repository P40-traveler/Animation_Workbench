export function selectionRect(start:{x:number;y:number},end:{x:number;y:number},width:number,height:number){
  const x1=Math.max(0,Math.min(width-1,start.x)),y1=Math.max(0,Math.min(height-1,start.y));
  const x2=Math.max(0,Math.min(width-1,end.x)),y2=Math.max(0,Math.min(height-1,end.y));
  return {x:Math.min(x1,x2),y:Math.min(y1,y2),width:Math.abs(x2-x1)+1,height:Math.abs(y2-y1)+1};
}
export function effectFrameAt(durations:number[],start:number,time:number){
  let t=time-start;
  for(let i=0;i<durations.length;i++){if(t>=0&&t<durations[i])return i;t-=durations[i]}
  return -1;
}
