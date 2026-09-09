import * as THREE from '/vendor/three.module.js';

// A process graph, not cluster telemetry: tubes carry evidence between agents.
export function createScene(container, {onSelect, paused = false}) {
  const scene = new THREE.Scene();
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);
  const camera = new THREE.PerspectiveCamera(34, 1, .1, 100);
  const graph = new THREE.Group();
  scene.add(graph, new THREE.HemisphereLight(0xffffff, 0x6d829e, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-3, 8, 7); scene.add(light);
  const mobile = container.clientWidth < 700;
  const positions = mobile ? [[-2.6,3.3],[.3,3.3],[2.9,1.6],[2.8,-1.1],[1.5,-3.4],[-1.5,-3.4],[-2.8,-.5]] : [[-4.4,1.8],[-1.4,2.7],[2,2.6],[4.7,.4],[2.6,-2.2],[-.8,-2.6],[-4.3,-1.4]];
  const nodes = [], labels = [], links = [], packets = [];
  let phase = 0, retry = false, visible = true, elapsed = 0;
  function label(text, index, point) {
    const canvas = document.createElement('canvas'); canvas.width=512; canvas.height=128;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle='#142b63'; ctx.textAlign='center'; ctx.font='600 48px system-ui';
    ctx.fillText(text,256,62,490);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace=THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map:texture, depthTest:false}));
    const pos=point||positions[index];
    sprite.position.set(pos[0], pos[1]-.8, .3);
    sprite.scale.set(2.6,.65,1); graph.add(sprite); return sprite;
  }
  positions.forEach(([x,y],i) => {
    const material = new THREE.MeshStandardMaterial({color:0xd9e4ef, metalness:.35, roughness:.28});
    const node = new THREE.Mesh(new THREE.CylinderGeometry(.53,.62,.25,6),material);
    node.rotation.x=Math.PI/2; node.position.set(x,y,0); node.userData.phase=i;
    graph.add(node); nodes.push(node);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(.36,.028,8,36), new THREE.MeshStandardMaterial({color:0xffffff,metalness:.3,roughness:.2}));
    ring.position.set(x,y,.17); graph.add(ring);
    labels.push(label(['01 Understand','02 Plan','03 Schedule','04 Generate','05 Execute','06 Analyze','07 Report'][i],i));
  });
  const coordinator=new THREE.Mesh(new THREE.CylinderGeometry(.82,.92,.4,8),new THREE.MeshStandardMaterial({color:0x368b73,metalness:.5,roughness:.24}));
  coordinator.rotation.x=Math.PI/2;coordinator.position.z=.15;graph.add(coordinator);
  const coordinatorLabel=label('ORCHESTRATOR',0,[0,-.15]);
  coordinatorLabel.scale.set(2.8,.7,1);
  function connection(points, isRetry=false) {
    const curve = new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));
    const material = new THREE.MeshStandardMaterial({color:isRetry ? 0xd89017 : 0xa9bad0, roughness:.4});
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve,64,.026,8,false),material);
    graph.add(mesh);
    const packet = new THREE.Mesh(new THREE.OctahedronGeometry(.1),new THREE.MeshBasicMaterial({color:isRetry ? 0xd89017 : 0x13a474}));
    graph.add(packet); packets.push({mesh:packet,curve,isRetry}); links.push(mesh);return mesh;
  }
  positions.forEach(([x,y],i) => {
    connection([[0,0,.05],[x*.45,y*.55,.25],[x,y,0]]);
  });
  const [sx,sy]=positions[2], [px,py]=positions[1];
  const retryLink=connection([[sx,sy,0],[sx,sy+.9,.3],[px,py+.9,.3],[px,py,0]],true);
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  let down=null;
  renderer.domElement.addEventListener('pointerdown',event=>{down={x:event.clientX,y:event.clientY,rotation:graph.rotation.y};});
  renderer.domElement.addEventListener('pointermove',event=>{
    if(down && event.buttons) graph.rotation.y=THREE.MathUtils.clamp(down.rotation+(event.clientX-down.x)*.003,-.35,.35);
  });
  renderer.domElement.addEventListener('pointerup',event=>{
    if(!down) return;
    const moved=Math.hypot(event.clientX-down.x,event.clientY-down.y); down=null;
    if(moved>6) return;
    const rect=renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObjects(nodes)[0]; if(hit) onSelect(hit.object.userData.phase);
  });
  renderer.domElement.addEventListener('pointercancel',()=>{down=null;});
  function resize() {
    const width=container.clientWidth,height=container.clientHeight;
    renderer.setSize(width,height); camera.aspect=width/height;
    const tangent=2*Math.tan(THREE.MathUtils.degToRad(17));
    const distance=Math.max((mobile?10:8.2)/tangent,(mobile?9:13.4)/(tangent*camera.aspect));
    camera.position.set(0,-.35,distance); camera.lookAt(0,-.35,0); camera.updateProjectionMatrix();
  }
  const observer=new ResizeObserver(resize); observer.observe(container); resize();
  const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;}); intersection.observe(container);
  let previous=performance.now();
  renderer.setAnimationLoop(now=>{
    const delta=THREE.MathUtils.clamp((now-previous)/1000,0,.05); previous=now;
    if(!visible || document.hidden) return;
    if(!paused) elapsed+=delta;
    nodes.forEach((node,i)=>{
      node.material.color.setHex(i===phase ? (retry ? 0xd89017 : 0x315fc9) : i<phase ? 0x13a474 : 0xcbd7e4);
      node.position.z=i===phase ? .1+Math.sin(elapsed*2)*.045 : 0;
    });
    retryLink.visible=retry;
    coordinator.rotation.z=Math.sin(elapsed*.5)*.04;
    packets.forEach(({mesh,curve,isRetry},i)=>{
      mesh.visible=isRetry ? retry : !retry && i<phase;
      mesh.position.copy(curve.getPointAt((elapsed*.3+i*.15)%1));
    });
    renderer.render(scene,camera);
  });
  return {
    setPhase(value) {phase=value; container.dataset.phase=String(value);},
    setRetry(value) {retry=value; container.dataset.retry=String(value);},
    setLabels(values) {
      labels.forEach(sprite=>{graph.remove(sprite); sprite.material.map.dispose(); sprite.material.dispose();});
      values.forEach((text,i)=>{labels[i]=label('0'+(i+1)+' '+text,i);});
    },
    setPaused(value) {paused=value;},
    reset() {graph.rotation.set(0,0,0);},
    dispose() {observer.disconnect(); intersection.disconnect(); renderer.setAnimationLoop(null); scene.traverse(object=>{object.geometry?.dispose(); if(object.material){object.material.map?.dispose(); object.material.dispose();}}); renderer.dispose(); renderer.domElement.remove();}
  };
}
