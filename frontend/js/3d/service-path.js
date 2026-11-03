/** Resolve endpoints on every frame; never capture moving-node coordinates. */
export function createServicePath({route,first,last,nodePosition,clientPosition,fallbackPosition,createArc,style}) {
    const endpoints=[];
    if(first)endpoints.push(()=>clientPosition(first));
    for(const node of route.positions){
        endpoints.push(()=>nodePosition(node.id)||fallbackPosition(node));
    }
    if(last)endpoints.push(()=>clientPosition(last));
    const segments=[];
    for(let index=1;index<endpoints.length;index++){
        segments.push(createArc({...style,from:endpoints[index-1],to:endpoints[index]}));
    }
    return {segments,update:()=>{for(const segment of segments)segment.update();}};
}
