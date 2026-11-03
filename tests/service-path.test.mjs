import test from 'node:test';
import assert from 'node:assert/strict';
import {createServicePath} from '../frontend/js/3d/service-path.js';

function fixture() {
    const nodes=new Map([['sat',{x:1}],['ground',{x:2}]]);
    const clients=new Map([[10,{x:0}],[20,{x:3}]]);
    let created=0;
    const path=createServicePath({
        route:{positions:[{id:'sat',x:100},{id:'ground',x:200}]},first:{id:10},last:{id:20},
        nodePosition:id=>nodes.get(id),clientPosition:client=>clients.get(client.id),
        fallbackPosition:node=>({x:node.x}),style:{dashed:false},
        createArc:({from,to})=>{created++;return {update(){this.ends=[from().x,to().x];}};}
    });
    return {path,nodes,clients,created:()=>created};
}

test('route endpoints track moved and replaced node markers without rebuilding geometry',()=>{
    const {path,nodes,created}=fixture();
    path.update();assert.deepEqual(path.segments.map(s=>s.ends),[[0,1],[1,2],[2,3]]);
    nodes.get('sat').x=7;nodes.set('ground',{x:9});
    path.update();assert.deepEqual(path.segments.map(s=>s.ends),[[0,7],[7,9],[9,3]]);
    assert.equal(created(),3);
});

test('both client access links stay attached to the current client positions',()=>{
    const {path,clients}=fixture();
    clients.set(10,{x:-4});clients.get(20).x=12;
    path.update();assert.equal(path.segments[0].ends[0],-4);assert.equal(path.segments.at(-1).ends[1],12);
});

test('unloaded topology marker uses its saved position until the live marker arrives',()=>{
    const {path,nodes}=fixture();nodes.delete('sat');
    path.update();assert.deepEqual(path.segments[0].ends,[0,100]);
    nodes.set('sat',{x:6});path.update();assert.deepEqual(path.segments[0].ends,[0,6]);
});
