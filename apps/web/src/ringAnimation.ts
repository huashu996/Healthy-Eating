/** CSS cubic-bezier(.22,1,.36,1), evaluated as y at the supplied x. */
export function ringEase(progress:number):number {
  if(progress<=0)return 0;
  if(progress>=1)return 1;
  let low=0,high=1,t=progress;
  for(let i=0;i<18;i++){
    t=(low+high)/2;
    const x=3*(1-t)*(1-t)*t*.22+3*(1-t)*t*t*.36+t*t*t;
    if(x<progress)low=t;else high=t;
  }
  return 1-Math.pow(1-t,3);
}
