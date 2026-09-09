import * as THREE from '/vendor/three.module.js';

// An illustrative agent system: geometry represents artifacts and tools, not live telemetry.
export function createScene(container, {onSelect, paused = false}) {
  const scene = new THREE.Scene();
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true, powerPreference:'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute('aria-hidden','true');
  container.appendChild(renderer.domElement);
  const camera = new THREE.OrthographicCamera(-8,8,5,-5,.1,80);
  camera.position.set(0,-10,22); camera.lookAt(0,0,0);
  const graph = new THREE.Group(); scene.add(graph);
  scene.add(new THREE.HemisphereLight(0xffffff,0x8194a9,1.8));
  const key = new THREE.DirectionalLight(0xfff5e9,2.0);
  key.position.set(-5,6,12); key.castShadow = true;
  key.shadow.mapSize.set(1024,1024); key.shadow.camera.left=-9; key.shadow.camera.right=9;
  key.shadow.camera.top=8; key.shadow.camera.bottom=-8; key.shadow.normalBias=.025;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xc8e7ff,1.0); fill.position.set(6,-3,7); scene.add(fill);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(30,24),new THREE.ShadowMaterial({opacity:.12}));
  floor.position.z=-.23; floor.receiveShadow=true; graph.add(floor);

  const colors = [0x328ee0,0x8770d3,0xe5aa36,0x21ad9c,0xe97b62,0x5990d9,0xc66b9e];
  const names = ['DOCUMENT','CONFIGURATION','RESOURCE POOL','CODE','EXECUTION','ANALYSIS','REPORTS'];
  const nodes=[], links=[], moving=[], labels=[];
  const geometry = {box:new THREE.BoxGeometry(1,1,1), cylinder:new THREE.CylinderGeometry(1,1,1,32), packet:new THREE.OctahedronGeometry(.065)};
  const materials = new Map();
  let phase=0, retry=false, elapsed=0, dirty=true, visible=true, mobile=null, disposed=false, contextLost=false;
  let hovered=-1, positions=[], down=null;
  const events = new AbortController();
  const labelLayer = document.createElement('div'); labelLayer.className='scene-label-layer'; container.appendChild(labelLayer);
  const mat = (color, metalness=.2, roughness=.32) => {
    const id=[color,metalness,roughness].join('/');
    if(!materials.has(id)) materials.set(id,new THREE.MeshStandardMaterial({color,metalness,roughness}));
    return materials.get(id);
  };
  const white=mat(0xfafcff,.25,.26), silver=mat(0xbdccd7,.65,.26), ink=mat(0x3b4e62,.25,.4);
  function mesh(parent, shape, material, xyz=[0,0,0], scale=[1,1,1]) {
    const object=new THREE.Mesh(shape,material); object.position.set(...xyz); object.scale.set(...scale);
    object.castShadow=true; object.receiveShadow=true; parent.add(object); return object;
  }
  const box=(parent,xyz,size,material=white)=>mesh(parent,geometry.box,material,xyz,size);
  function cylinder(parent,radius,depth,z,material,sides=32) {
    const shape=sides===32?geometry.cylinder:new THREE.CylinderGeometry(1,1,1,sides);
    const object=mesh(parent,shape,material,[0,0,z],[radius,depth,radius]); object.rotation.x=Math.PI/2; return object;
  }
  function ring(parent,radius,tube,z,color,arc=Math.PI*2) {
    return mesh(parent,new THREE.TorusGeometry(radius,tube,6,64,arc),mat(color,.45,.25),[0,0,z]);
  }
  function panel(parent,x,y,z,w,h,d,material=white) {
    const r=Math.min(.07,w/5,h/5), shape=new THREE.Shape();
    shape.moveTo(-w/2+r,-h/2); shape.lineTo(w/2-r,-h/2); shape.quadraticCurveTo(w/2,-h/2,w/2,-h/2+r);
    shape.lineTo(w/2,h/2-r); shape.quadraticCurveTo(w/2,h/2,w/2-r,h/2);
    shape.lineTo(-w/2+r,h/2); shape.quadraticCurveTo(-w/2,h/2,-w/2,h/2-r);
    shape.lineTo(-w/2,-h/2+r); shape.quadraticCurveTo(-w/2,-h/2,-w/2+r,-h/2);
    const shape3d=new THREE.ExtrudeGeometry(shape,{depth:d,bevelEnabled:true,bevelThickness:.025,bevelSize:.025,bevelSegments:2,steps:1});
    shape3d.translate(0,0,-d/2);
    return mesh(parent,shape3d,material,[x,y,z]);
  }
  function blocks(parent,items,material,shape=geometry.box) {
    const object=new THREE.InstancedMesh(shape,material,items.length), dummy=new THREE.Object3D();
    items.forEach(([x,y,z,w,h,d],i)=>{dummy.position.set(x,y,z);dummy.scale.set(w,h,d);dummy.updateMatrix();object.setMatrixAt(i,dummy.matrix);});
    object.castShadow=true; object.receiveShadow=true; parent.add(object); return object;
  }
  function strokes(parent,items,color) { return blocks(parent,items,mat(color,.05,.65)); }
  function textSurface(parent,text,x,y,z,w,h,color='#405566',background=null) {
    const canvas=document.createElement('canvas'); canvas.width=512; canvas.height=160;
    const ctx=canvas.getContext('2d');
    if(background) {ctx.fillStyle=background;ctx.fillRect(0,0,512,160);}
    ctx.fillStyle=color;ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='600 64px ui-monospace, monospace';ctx.fillText(text,256,80,490);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const surface=mesh(parent,new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false}),[x,y,z]);
    surface.castShadow=false; surface.receiveShadow=false; return surface;
  }
  function pedestal(parent,color,index) {
    cylinder(parent,1.0,.14,-.08,silver,6);
    cylinder(parent,.98,.18,.035,white,6);
    const top=cylinder(parent,.90,.065,.16,mat(new THREE.Color(color).lerp(new THREE.Color(0xffffff),.76).getHex()),6);
    top.rotation.y=Math.PI/6;
    const indicator=ring(parent,.81,.018,.215,color,Math.PI*1.48); indicator.rotation.z=-Math.PI*.7;
    const screws=Array.from({length:6},(_,i)=>{const a=i*Math.PI/3;return [Math.cos(a)*.83,Math.sin(a)*.83,.23,.035,.035,.025];});
    blocks(parent,screws,silver);
    textSurface(parent,String(index+1).padStart(2,'0'),0,-.77,.235,.30,.10,'#677c8b');
    return indicator;
  }
  function documentAgent(group,color) {
    const pages=new THREE.Group(); pages.rotation.z=-.14;group.add(pages);
    for(let i=0;i<3;i++)panel(pages,-.12+i*.08,.06+i*.025,.32+i*.095,.95,1.14,.055,i===2?white:mat(0xcbdff0));
    strokes(pages,[[0,.43,.58,.57,.07,.012],[-.10,.22,.58,.36,.025,.012],[0,.10,.58,.57,.025,.012],[-.04,-.03,.58,.49,.025,.012],[0,-.17,.58,.57,.025,.012],[-.13,-.30,.58,.31,.025,.012]],color);
    const tab=panel(group,.53,.22,.7,.36,.42,.08,mat(color)); tab.rotation.z=.14;
    strokes(tab,[[0,.065,.075,.21,.023,.01],[0,-.02,.075,.21,.023,.01]],0xffffff);
    const scan=box(pages,[0,.23,.605],[.73,.025,.02],mat(0x50c5cd));
    moving.push(time=>{scan.position.y=Math.sin(time*1.4)*.38;});
  }
  function configurationAgent(group,color) {
    panel(group,0,0,.34,1.36,1.04,.1);
    strokes(group,[-.30,0,.30].map(y=>[0,y,.42,1.05,.035,.035]),0xbbc9d9);
    const tick=[];[-.30,0,.30].forEach(y=>{for(let x=-.45;x<=.46;x+=.15)tick.push([x,y-.09,.41,.012,.035,.02]);});strokes(group,tick,0xa7b6c9);
    [-.28,.19,-.06].forEach((x,i)=>{
      const knob=new THREE.Group();knob.position.set(x,.30-i*.30,.43);group.add(knob);
      cylinder(knob,.13,.07,0,mat(color));cylinder(knob,.075,.035,.052,white);
      moving.push(time=>{knob.position.x=x+Math.sin(time*.7+i)*.035;});
    });
    const tag=panel(group,.56,.48,.60,.36,.24,.045,mat(0xf0c259));tag.rotation.z=.08;
    textSurface(tag,'{ }',0,0,.055,.26,.10,'#72501a');
  }
  function resourceAgent(group,color) {
    const towers=[];
    for(let x=0;x<3;x++)for(let y=0;y<2;y++) {
      const px=(x-1)*.40,py=(y-.5)*.48,height=.22+(x===1?.20:0)+(y===1?.12:0);
      towers.push([px,py,.25+height/2,.31,.35,height]);
      box(group,[px,py,.26+height],[.32,.36,.055],mat(color));
      box(group,[px,py-.183,.28+height/2],[.12,.014,.035],mat(x===1?0x38ad99:0xffffff));
    }
    blocks(group,towers,white);
    const bridge=box(group,[0,0,.97],[1.17,.025,.025],mat(0xdbc287));
    moving.push(time=>{bridge.position.y=Math.sin(time*.8)*.38;});
    textSurface(group,'POOL',0,-.56,.27,.58,.16,'#917133');
  }
  function codeAgent(group,color) {
    const terminal=new THREE.Group();terminal.position.set(0,.05,.39);terminal.rotation.x=-.14;group.add(terminal);
    panel(terminal,0,0,.1,1.36,1.02,.13,silver);
    panel(terminal,0,0,.19,1.23,.89,.03,mat(0x263746,.15,.5));
    const rows=[[0,.30,.245,.92,.018,.01],[-.24,.16,.245,.40,.034,.01],[-.04,.04,.245,.53,.034,.01],[.04,-.08,.245,.64,.034,.01],[-.10,-.20,.245,.41,.034,.01]];
    strokes(terminal,[rows[0]],0x687d8b);strokes(terminal,rows.slice(1,3),0x6ed7c6);strokes(terminal,rows.slice(3),0xf1c37e);
    const cursor=box(terminal,[.33,-.20,.25],[.06,.075,.014],mat(0x9edce3));
    moving.push(time=>{cursor.visible=Math.sin(time*3)>.05;});
    panel(group,0,-.56,.28,1.15,.28,.06,white);
    blocks(group,Array.from({length:7},(_,i)=>[-.45+i*.15,-.55,.325,.09,.08,.025]),mat(0x77bbae));
    const badge=panel(group,.62,.42,.84,.40,.31,.04,mat(color));textSurface(badge,'</>',0,0,.055,.30,.14,'#ffffff');
  }
  function executionAgent(group,color) {
    cylinder(group,.55,.18,.38,white);ring(group,.49,.034,.5,color);
    const rotor=ring(group,.63,.02,.37,0xe6a394,Math.PI*1.4);
    const triangle=new THREE.Shape();triangle.moveTo(-.12,-.23);triangle.lineTo(.26,0);triangle.lineTo(-.12,.23);triangle.closePath();
    mesh(group,new THREE.ExtrudeGeometry(triangle,{depth:.14,bevelEnabled:true,bevelThickness:.025,bevelSize:.025,bevelSegments:2}),mat(color),[0,0,.50]);
    moving.push(time=>{rotor.rotation.z=-time*.3;});
    [-.43,0,.43].forEach((x,i)=>{panel(group,x,-.55,.28,.28,.16,.04,mat([0x66b8ac,color,0xd4dce3][i]));});
    textSurface(group,'RUN',0,.63,.30,.49,.13,'#aa5b4d');
  }
  function analysisAgent(group,color) {
    panel(group,-.06,.05,.30,1.30,1.10,.06);
    strokes(group,[-.25,0,.25,.50].map(y=>[-.08,y,.37,1.07,.011,.01]),0xd9e2ec);
    const bars=[.34,.55,.83];
    bars.forEach((height,i)=>box(group,[-.42+i*.31,-.35+height/2,.42],[.17,height,.15],mat([0x8cb6e8,color,0x3eaeaa][i])));
    const lens=new THREE.Group();lens.position.set(.43,.21,.93);group.add(lens);
    ring(lens,.28,.047,0,0xd6b25b);
    const glass=mesh(lens,new THREE.CircleGeometry(.25,32),new THREE.MeshBasicMaterial({color:0xb3e7f5,transparent:true,opacity:.32,depthWrite:false}));
    const handle=box(lens,[.27,-.28,0],[.1,.35,.1],mat(0x4d7699));handle.rotation.z=.75;
    moving.push(time=>{lens.position.x=.36+Math.sin(time*.7)*.09;glass.material.opacity=.25+Math.sin(time)*.04;});
  }
  function reportAgent(group,color) {
    [-.37,.37].forEach((x,i)=>{
      const report=new THREE.Group();report.position.set(x,.03,.38+i*.06);report.rotation.z=i?-.12:.12;group.add(report);
      panel(report,0,0,0,.67,1.03,.095);
      box(report,[0,.31,.065],[.51,.18,.035],mat(i?0x44b5ad:color));
      textSurface(report,i?'VS':'LOG',0,.31,.09,.36,.10,'#ffffff');
      strokes(report,[[0,.11,.085,.45,.022,.012],[0,-.02,.085,.45,.022,.012],[-.08,-.15,.085,.29,.022,.012]],0xa9b8c8);
      if(i)blocks(report,[[ -.15,-.31,.095,.08,.14,.05],[0,-.27,.095,.08,.23,.05],[.15,-.23,.095,.08,.31,.05]],mat(0x59b6b2));
      else strokes(report,[[-.08,-.31,.085,.29,.026,.01]],color);
    });
  }
  const models=[documentAgent,configurationAgent,resourceAgent,codeAgent,executionAgent,analysisAgent,reportAgent];
  models.forEach((build,i)=>{
    const root=new THREE.Group();root.userData.phase=i;graph.add(root);
    const indicator=pedestal(root,colors[i],i), sculpture=new THREE.Group();root.add(sculpture);build(sculpture,colors[i]);
    nodes.push({root,sculpture,indicator});
    const button=document.createElement('button');button.type='button';button.className='scene-node-label';button.dataset.scenePhase=String(i);
    button.style.setProperty('--agent-color','#'+colors[i].toString(16));
    const small=document.createElement('small'),name=document.createElement('span');small.textContent='0'+(i+1)+' / '+names[i];name.textContent=names[i];
    button.append(small,name);labelLayer.appendChild(button);labels.push(button);
    button.addEventListener('click',()=>onSelect(i),{signal:events.signal});
    button.addEventListener('pointerenter',()=>{hovered=i;dirty=true;},{signal:events.signal});
    button.addEventListener('pointerleave',()=>{hovered=-1;dirty=true;},{signal:events.signal});
  });

  const coordinator=new THREE.Group();graph.add(coordinator);
  cylinder(coordinator,1.17,.15,-.06,silver,8);cylinder(coordinator,1.11,.21,.12,white,8);
  cylinder(coordinator,.91,.12,.29,mat(0xbfe3dd),8);
  const innerRing=ring(coordinator,.77,.024,.40,0x429d90), outerRing=ring(coordinator,1.04,.019,.30,0xdbc080,Math.PI*1.68);
  const chip=panel(coordinator,0,0,.51,.85,.85,.21,mat(0x2d746e,.48,.24));chip.rotation.z=Math.PI/4;
  const core=mesh(coordinator,new THREE.OctahedronGeometry(.39),mat(0x73c7ba,.5,.22),[0,0,.96]);
  const pins=[];for(let i=0;i<7;i++) {const x=-.35+i*.115;pins.push([x,-.53,.48,.04,.14,.055],[x,.53,.48,.04,.14,.055],[-.53,x,.48,.14,.04,.055],[.53,x,.48,.14,.04,.055]);}
  blocks(coordinator,pins,mat(0xdcc389,.65,.24));
  const sockets=[];for(let i=0;i<8;i++){const a=i*Math.PI/4;sockets.push([Math.cos(a)*.96,Math.sin(a)*.96,.33,.085,.085,.04]);}
  blocks(coordinator,sockets,mat(0x2b9c8b));
  const hubLabel=document.createElement('div');hubLabel.className='scene-hub-label';hubLabel.innerHTML='<small>MULTI-AGENT</small><b>ORCHESTRATOR</b>';labelLayer.appendChild(hubLabel);
  const packetMesh=new THREE.InstancedMesh(geometry.packet,new THREE.MeshBasicMaterial({color:0xffffff}),64);
  packetMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);packetMesh.frustumCulled=false;graph.add(packetMesh);
  const dummy=new THREE.Object3D(), vector=new THREE.Vector3();
  function connection(start,end,index,kind) {
    const a=new THREE.Vector3(...start),b=new THREE.Vector3(...end);
    const mid=a.clone().lerp(b,.5);
    if(kind==='retry') {mid.y+=2.1;mid.z=.76;}
    else if(kind==='handoff') {mid.x*=1.23;mid.y*=1.23;mid.z=.07;}
    else {mid.x+=kind==='return'?-.19:.19;mid.y+=kind==='return'?.14:-.14;mid.z=kind==='return'?.14:.34;}
    const curve=new THREE.QuadraticBezierCurve3(a,mid,b);
    const material=new THREE.MeshStandardMaterial({color:kind==='retry'?0xd78c24:colors[index],transparent:true,opacity:.5,roughness:.38,metalness:.22});
    const line=mesh(graph,new THREE.TubeGeometry(curve,32,kind==='retry'?.032:kind==='handoff'?.013:.021,5,false),material);
    line.castShadow=false;line.receiveShadow=false;
    links.push({line,curve,index,kind});
  }
  function layout(compact) {
    positions=compact?[[-2.25,4.2],[1.85,4.2],[2.45,.8],[2.45,-2.9],[0,-5.2],[-2.45,-2.9],[-2.45,.8]]:[[-5.15,2.30],[-1.9,3.6],[2.25,3.45],[5.2,.45],[3.2,-2.65],[-.55,-3.25],[-4.75,-1.70]];
    positions.forEach(([x,y],i)=>nodes[i].root.position.set(x,y,0));
    links.forEach(({line})=>{graph.remove(line);line.geometry.dispose();line.material.dispose();});links.length=0;
    positions.forEach(([x,y],i)=>{
      connection([0,0,.23],[x,y,.22],i,'call');connection([x,y,.19],[0,0,.18],i,'return');
      if(i<6)connection([x,y,-.03],[...positions[i+1],-.03],i,'handoff');
    });
    connection([...positions[2],.27],[...positions[1],.27],1,'retry');
    dirty=true;
  }
  function resize() {
    const width=container.clientWidth,height=container.clientHeight;if(!width||!height)return;
    const compact=width<700;
    if(mobile!==compact){mobile=compact;layout(compact);}
    renderer.setSize(width,height);const aspect=width/height;
    const viewHeight=Math.max(compact?13.8:9.4,(compact?8.5:15.8)/aspect);
    camera.left=-viewHeight*aspect/2;camera.right=viewHeight*aspect/2;camera.top=viewHeight/2;camera.bottom=-viewHeight/2;camera.updateProjectionMatrix();dirty=true;
  }
  function positionLabels() {
    graph.updateMatrixWorld(true);
    nodes.forEach(({root},i)=>{
      vector.set(0,-1.12,.02);root.localToWorld(vector);vector.project(camera);
      labels[i].style.left=((vector.x+1)/2*container.clientWidth)+'px';labels[i].style.top=((-vector.y+1)/2*container.clientHeight)+'px';
      labels[i].setAttribute('aria-pressed',String(i===phase));
    });
    vector.set(0,mobile?-1.75:-1.34,.04);graph.localToWorld(vector);vector.project(camera);
    hubLabel.style.left=((vector.x+1)/2*container.clientWidth)+'px';hubLabel.style.top=((-vector.y+1)/2*container.clientHeight)+'px';
  }
  const raycaster=new THREE.Raycaster(), pointer=new THREE.Vector2();
  function hitTest(event) {
    const rect=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    let hit=raycaster.intersectObjects(nodes.map(node=>node.root),true)[0]?.object;
    while(hit && hit.userData.phase===undefined)hit=hit.parent;
    return hit?.userData.phase??-1;
  }
  renderer.domElement.addEventListener('pointerdown',event=>{down={x:event.clientX,y:event.clientY,rotationX:graph.rotation.x,rotationY:graph.rotation.y};renderer.domElement.setPointerCapture(event.pointerId);},{signal:events.signal});
  renderer.domElement.addEventListener('pointermove',event=>{
    if(down){graph.rotation.y=THREE.MathUtils.clamp(down.rotationY+(event.clientX-down.x)*.002,-.25,.25);graph.rotation.x=THREE.MathUtils.clamp(down.rotationX+(event.clientY-down.y)*.001,-.10,.14);}
    else hovered=hitTest(event);
    renderer.domElement.style.cursor=down?'grabbing':hovered>=0?'pointer':'grab';dirty=true;
  },{signal:events.signal});
  renderer.domElement.addEventListener('pointerup',event=>{
    if(!down)return;const moved=Math.hypot(event.clientX-down.x,event.clientY-down.y);down=null;
    if(renderer.domElement.hasPointerCapture(event.pointerId))renderer.domElement.releasePointerCapture(event.pointerId);
    if(moved<=6){const index=hitTest(event);if(index>=0)onSelect(index);}
    dirty=true;
  },{signal:events.signal});
  renderer.domElement.addEventListener('pointercancel',()=>{down=null;dirty=true;},{signal:events.signal});
  renderer.domElement.addEventListener('pointerleave',()=>{hovered=-1;dirty=true;},{signal:events.signal});
  renderer.domElement.addEventListener('webglcontextlost',event=>{
    event.preventDefault();contextLost=true;renderer.setAnimationLoop(null);labelLayer.hidden=true;renderer.domElement.hidden=true;
    container.dispatchEvent(new CustomEvent('scene:unavailable'));
  },{signal:events.signal});
  const observer=new ResizeObserver(resize);observer.observe(container);resize();
  const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;dirty=true;});intersection.observe(container);
  let previous=performance.now();
  renderer.setAnimationLoop(now=>{
    const delta=THREE.MathUtils.clamp((now-previous)/1000,0,.05);previous=now;
    if(disposed||contextLost||!visible||document.hidden||paused&&!dirty)return;
    if(!paused)elapsed+=delta;
    nodes.forEach(({sculpture,indicator},i)=>{
      const lift=(i===phase?.15:0)+(i===hovered?.08:0);
      sculpture.position.z=paused?lift:THREE.MathUtils.lerp(sculpture.position.z,lift,delta*8);
      indicator.rotation.z=-Math.PI*.7+(i===phase?elapsed*.16:0);
    });
    moving.forEach(animate=>animate(elapsed));core.rotation.z=elapsed*.22;core.rotation.y=Math.sin(elapsed*.5)*.13;
    innerRing.rotation.z=elapsed*.08;outerRing.rotation.z=-elapsed*.05;
    let count=0;
    links.forEach(({line,curve,index,kind})=>{
      const active=kind==='retry'?retry:kind==='handoff'?index<phase:index===phase;
      line.visible=kind!=='retry'||retry;
      line.material.opacity=kind==='retry'?.95:kind==='handoff'?.2:active?.8:.3;
      if(!active)return;
      for(let j=0;j<2;j++){
        const t=(elapsed*(kind==='return'?.19:.25)+j*.5+index*.1)%1;
        dummy.position.copy(curve.getPoint(t));dummy.rotation.set(elapsed*.5,elapsed*.3,0);dummy.scale.setScalar(kind==='handoff'?.7:1);dummy.updateMatrix();
        packetMesh.setMatrixAt(count,dummy.matrix);packetMesh.setColorAt(count,new THREE.Color(kind==='retry'?0xe0a125:colors[index]));count++;
      }
    });
    packetMesh.count=count;packetMesh.instanceMatrix.needsUpdate=true;if(packetMesh.instanceColor)packetMesh.instanceColor.needsUpdate=true;
    renderer.render(scene,camera);positionLabels();dirty=false;
  });
  container.dataset.detail='sculpted-agents';container.dataset.agentCount=String(nodes.length);
  return {
    setPhase(value){phase=value;container.dataset.phase=String(value);dirty=true;},
    setRetry(value){retry=value;container.dataset.retry=String(value);dirty=true;},
    setLabels(values){values.forEach((text,i)=>{labels[i].querySelector('span').textContent=text;labels[i].setAttribute('aria-label',text);});dirty=true;},
    setPaused(value){paused=value;dirty=true;},
    reset(){graph.rotation.set(0,0,0);hovered=-1;dirty=true;},
    dispose(){
      disposed=true;events.abort();observer.disconnect();intersection.disconnect();renderer.setAnimationLoop(null);
      const shapes=new Set(),surfaces=new Set(),textures=new Set();
      scene.traverse(object=>{if(object.geometry)shapes.add(object.geometry);if(object.material)(Array.isArray(object.material)?object.material:[object.material]).forEach(material=>{surfaces.add(material);if(material.map)textures.add(material.map);});});
      shapes.forEach(shape=>shape.dispose());surfaces.forEach(surface=>surface.dispose());textures.forEach(texture=>texture.dispose());
      renderer.dispose();renderer.domElement.remove();labelLayer.remove();
    }
  };
}
