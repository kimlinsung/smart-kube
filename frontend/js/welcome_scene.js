import * as THREE from '/vendor/three.module.js';

export function createScene(container, { onSelect, paused = false }) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#f3f5f3');
  const camera = new THREE.PerspectiveCamera(34, 1, .1, 100);
  const renderer = new THREE.WebGLRenderer({ antialias:true, alpha:false, powerPreference:'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.6));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.35;
  renderer.domElement.setAttribute('aria-hidden','true');
  container.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff,0x8c9f91,3));
  const key = new THREE.DirectionalLight(0xffffff,5);
  key.position.set(-4,9,5); key.castShadow = true;
  key.shadow.mapSize.set(1024,1024);
  Object.assign(key.shadow.camera,{left:-8,right:8,top:7,bottom:-7,near:.1,far:30});
  key.shadow.bias = -.001;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff,3);
  rim.position.set(6,4,-5); scene.add(rim);
  const world = new THREE.Group(); scene.add(world);
  const materials = {
    silver:new THREE.MeshStandardMaterial({color:0xd0d7d4,metalness:.62,roughness:.32}),
    dark:new THREE.MeshStandardMaterial({color:0x263b32,metalness:.5,roughness:.4}),
    white:new THREE.MeshStandardMaterial({color:0xf8faf7,metalness:.18,roughness:.33}),
    copper:new THREE.MeshStandardMaterial({color:0xc58c65,metalness:.6,roughness:.34}),
    edge:new THREE.MeshStandardMaterial({color:0x138777,metalness:.45,roughness:.3}),
    blue:new THREE.MeshStandardMaterial({color:0x5279aa,metalness:.45,roughness:.35}),
    light:new THREE.MeshStandardMaterial({color:0x64d5b9,emissive:0x22a885,emissiveIntensity:.5}),
  };
  const boxGeo = new THREE.BoxGeometry(1,1,1);
  function box(group,x,y,z,w,h,d,material) {
    const mesh = new THREE.Mesh(boxGeo,material);
    mesh.position.set(x,y,z); mesh.scale.set(w,h,d);
    mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh); return mesh;
  }
  function label(group,text,x,y,z,width) {
    const canvas = document.createElement('canvas'); canvas.width=512;canvas.height=128;
    const ctx=canvas.getContext('2d');
    ctx.fillStyle='#f7faf7';ctx.fillRect(0,0,512,128);
    ctx.fillStyle='#304b3d';ctx.font='500 42px monospace';ctx.textAlign='center';ctx.fillText(text,256,80);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(width,width/4),new THREE.MeshBasicMaterial({map:texture}));
    mesh.rotation.x=-Math.PI/2;mesh.position.set(x,y,z);group.add(mesh);
  }
  const assemblies=[];
  const electronics=[];
  const tierColors=[0xc58c65,0x138777,0x5279aa];
  [-3.55,0,3.55].forEach((x,index) => {
    const group=new THREE.Group();group.position.set(x,0,index===1?.4:0);
    group.userData.tier=index;
    world.add(group);assemblies.push(group);
    box(group,0,-.09,0,2.65,.16,2.3,materials.silver);
    box(group,0,.03,0,2.53,.08,2.18,materials.white);
    label(group,['DEVICE','EDGE','CLOUD'][index],0,.077,.78,1.15);
    const interior=new THREE.Group();group.add(interior);electronics.push(interior);
  });
  const device=electronics[0];
  box(device,0,.22,-.22,1.65,.22,1.12,materials.copper);
  box(device,0,.38,-.22,1.52,.13,1.02,materials.dark);
  box(device,-.25,.74,-.38,.85,.65,.68,materials.white);
  const lens=new THREE.Mesh(new THREE.CylinderGeometry(.23,.26,.24,40),materials.dark);
  lens.rotation.x=Math.PI/2;lens.position.set(-.25,.77,.06);device.add(lens);
  const glass=new THREE.Mesh(new THREE.CylinderGeometry(.155,.155,.025,40),materials.blue);
  glass.rotation.x=Math.PI/2;glass.position.set(-.25,.77,.195);device.add(glass);
  for(let i=0;i<5;i++)box(device,.49,.49,-.59+i*.18,.26,.12,.07,materials.silver);
  box(device,.58,.91,-.47,.035,.92,.035,materials.dark);
  box(device,-.49,.465,.2,.08,.02,.05,materials.light);
  const edge=electronics[1];
  box(edge,0,.27,-.25,1.9,.35,1.25,materials.dark);
  box(edge,0,.49,-.25,1.85,.08,1.2,materials.edge);
  box(edge,-.18,.63,-.35,.85,.18,.72,materials.copper);
  for(let i=0;i<10;i++)box(edge,-.66+i*.12,.83,-.35,.045,.33,.89,materials.silver);
  for(let i=0;i<4;i++)box(edge,-.57+i*.4,.29,.394,.24,.14,.055,materials.silver);
  box(edge,.63,.55,.11,.15,.035,.11,materials.light);
  const cloud=electronics[2];
  for(let i=0;i<4;i++){
    const y=.32+i*.4;
    box(cloud,0,y,-.22,1.95,.34,1.25,materials.silver);
    box(cloud,0,y,.423,1.85,.25,.05,materials.dark);
    for(let j=0;j<9;j++)box(cloud,-.74+j*.14,y,.455,.038,.16,.01,materials.silver);
    box(cloud,.72,y,.465,.065,.055,.02,materials.light);
  }
  box(cloud,0,1.83,-.22,1.97,.1,1.26,materials.white);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(100,100),new THREE.ShadowMaterial({opacity:.12}));
  floor.rotation.x=-Math.PI/2;floor.position.y=-.19;scene.add(floor);
  const tracks=[],packets=[];
  for(let i=0;i<2;i++){
    const points=[new THREE.Vector3(-2.2+i*3.55,.02,.0),new THREE.Vector3(-1.86+i*3.55,.02,.0),new THREE.Vector3(-1.69+i*3.55,.02,.4),new THREE.Vector3(-1.33+i*3.55,.02,.4)];
    const curve=new THREE.CatmullRomCurve3(points);
    const material=new THREE.MeshStandardMaterial({color:0x9aafa0,metalness:.3,roughness:.4});
    const tube=new THREE.Mesh(new THREE.TubeGeometry(curve,28,.025,6,false),material);
    world.add(tube);tracks.push({curve,material});
    for(let j=0;j<3;j++){
      const packet=box(world,0,0,0,.09,.045,.09,materials.edge);
      packets.push({mesh:packet,curve,offset:j/3+i*.1});
    }
  }
  // A paper-like stack physically separates as the workflow produces artifacts.
  const sheets=[];
  for(let i=0;i<3;i++){
    const sheet=box(world,-.03,.12+i*.025,2,1.3,.02,.83,materials.white);
    sheet.rotation.y=-.1+i*.06;sheets.push(sheet);
    for(let j=0;j<4;j++)box(sheet,-.25,1,.28-j*.18,.55-j*.06,.1,.03,materials.silver);
  }
  let selected=-1,phase=0,targetRotation=-.16,targetTilt=0,visible=true,frame=0,last=0,elapsed=0;
  let drag=null,disposed=false;
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  function requestFrame(){if(!frame&&!disposed)frame=requestAnimationFrame(render);}
  function resize(){
    const w=container.clientWidth,h=container.clientHeight;
    if(!w||!h)return;
    renderer.setSize(w,h,false);camera.aspect=w/h;
    const distance=Math.max(9.3,17.6/camera.aspect);
    camera.position.set(0,distance*.55,distance);
    camera.fov=34;
    camera.lookAt(0,.2,0);camera.updateProjectionMatrix();requestFrame();
  }
  function render(now){
    frame=0;
    const dt=Math.min((now-last)/1000,.05)||0;last=now;
    if(!paused)elapsed+=dt;
    const smoothing=paused?1:1-Math.exp(-dt*6);
    world.rotation.y+=(targetRotation+(paused?0:Math.sin(elapsed*.16)*.045)-world.rotation.y)*smoothing;
    world.rotation.x+=(targetTilt-world.rotation.x)*smoothing;
    assemblies.forEach((group,index)=>{
      const lift=index===selected?.2:0;
      group.position.y+=(lift-group.position.y)*smoothing;
      const scale=selected<0||index===selected?1:.95;
      group.scale.lerp(new THREE.Vector3(scale,scale,scale),smoothing);
      electronics[index].position.y=((phase===3||phase===5)?.11:0)+(paused?0:Math.sin(elapsed*.8+index)*.015);
    });
    tracks.forEach(({material})=>material.color.setHex(phase>=2?0x369985:0x9aafa0));
    packets.forEach(({mesh,curve,offset})=>{
      mesh.position.copy(curve.getPoint((elapsed*.18+offset)%1));
      mesh.visible=phase>=2;
    });
    sheets.forEach((sheet,index)=>{sheet.position.y=.12+index*(phase>=3?.09:.025);});
    renderer.render(scene,camera);
    renderer.domElement.dataset.phase=String(phase);
    renderer.domElement.dataset.tier=String(selected);
    if(visible&&!document.hidden&&!paused)requestFrame();
  }
  function down(event){if(event.button!==0)return;drag={x:event.clientX,y:event.clientY,rotation:targetRotation,tilt:targetTilt,moved:false};}
  function move(event){
    if(!drag)return;
    const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
    if(Math.abs(dx)+Math.abs(dy)>6)drag.moved=true;
    targetRotation=Math.max(-.85,Math.min(.85,drag.rotation+dx*.005));
    if(event.pointerType!=='touch')targetTilt=Math.max(-.12,Math.min(.16,drag.tilt+dy*.0015));
    requestFrame();
  }
  function up(event){
    if(!drag)return;
    if(!drag.moved){
      const r=renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);
      raycaster.setFromCamera(pointer,camera);
      const hit=raycaster.intersectObjects(assemblies,true)[0];
      if(hit){let obj=hit.object;while(obj&&obj.userData.tier===undefined)obj=obj.parent;if(obj)onSelect(obj.userData.tier);}
    }
    drag=null;
  }
  container.addEventListener('pointerdown',down);
  window.addEventListener('pointermove',move);
  window.addEventListener('pointerup',up);
  container.addEventListener('pointercancel',()=>{drag=null;});
  const observer=new ResizeObserver(resize);observer.observe(container);
  const visibility=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible){last=performance.now();requestFrame();}});
  visibility.observe(container);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){last=performance.now();requestFrame();}});
  renderer.domElement.addEventListener('webglcontextlost',event=>{
    event.preventDefault();paused=true;renderer.domElement.hidden=true;
    document.getElementById('sceneFallback').hidden=false;
  });
  window.addEventListener('pagehide',event=>{
    if(event.persisted)return;
    disposed=true;cancelAnimationFrame(frame);observer.disconnect();visibility.disconnect();
    window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);
    const geometries=new Set(),mats=new Set();
    scene.traverse(obj=>{if(obj.geometry)geometries.add(obj.geometry);if(obj.material)mats.add(obj.material);});
    geometries.forEach(g=>g.dispose());mats.forEach(m=>{m.map?.dispose();m.dispose();});renderer.dispose();
  },{once:true});
  resize();
  return {
    setTier(value){selected=value;requestFrame();},
    setPhase(value){phase=value;requestFrame();},
    setPaused(value){paused=value;last=performance.now();requestFrame();},
    reset(){targetRotation=-.16;targetTilt=0;requestFrame();}
  };
}
