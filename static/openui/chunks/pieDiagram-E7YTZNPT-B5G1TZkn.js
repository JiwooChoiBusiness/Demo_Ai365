import{p as tt}from"./chunk-JWPE2WC7-BQRyKMhJ.js";import{g as et,s as at,a as it,b as rt,o as lt,n as st,_ as n,l as R,c as nt,A as ot,D as ct,E as dt,d as pt,p as ht,B as gt}from"./mermaid.core-a7IuLF6e.js";import{p as ut}from"./cynefin-OW5HDTMX-CamUxOHq.js";import{d as j,o as mt,a as ft}from"./main-DI52pZY0.js";var xt=gt.pie,H={sections:new Map,showData:!1},D=H.sections,W=H.showData,wt=structuredClone(xt),St=n(()=>structuredClone(wt),"getConfig"),$t=n(()=>{D=new Map,W=H.showData,ht()},"clear"),bt=n(({label:t,value:a})=>{if(a<0)throw new Error(`"${t}" has invalid value: ${a}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);D.has(t)||(D.set(t,a),R.debug(`added new section: ${t}, with value: ${a}`))},"addSection"),vt=n(()=>D,"getSections"),yt=n(t=>{W=t},"setShowData"),Ct=n(()=>W,"getShowData"),q={getConfig:St,clear:$t,setDiagramTitle:st,getDiagramTitle:lt,setAccTitle:rt,getAccTitle:it,setAccDescription:at,getAccDescription:et,addSection:bt,getSections:vt,setShowData:yt,getShowData:Ct},Dt=n((t,a)=>{tt(t,a),a.setShowData(t.showData),t.sections.map(a.addSection)},"populateDb"),Tt={parse:n(async t=>{const a=await ut("pie",t);R.debug(a),Dt(a,q)},"parse")},kt=n(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieCircle.highlighted{
    scale: 1.05;
    opacity: 1;
  }
  .pieCircle.highlightedOnHover:hover{
    transition-duration: 250ms;
    scale: 1.05;
    opacity: 1;
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),At=kt,Mt=n(t=>{const a=[...t.values()].reduce((c,g)=>c+g,0),B=[...t.entries()].map(([c,g])=>({label:c,value:g})).filter(c=>c.value/a*100>=1);return ft().value(c=>c.value).sort(null)(B)},"createPieArcs"),Ot=n((t,a,B,c)=>{R.debug(`rendering pie chart
`+t);const g=c.db,E=nt(),u=ot(g.getConfig(),E.pie),F=40,r=18,o=4,b=450,w=b,T=ct(a),v=T.append("g");v.attr("transform","translate("+w/2+","+b/2+")");const{themeVariables:l}=E;let[k]=dt(l.pieOuterStrokeWidth);k??(k=2);const G=u.legendPosition,P=u.textPosition,I=u.donutHole>0&&u.donutHole<=.9?u.donutHole:0,m=Math.min(w,b)/2-F,J=j().innerRadius(I*m).outerRadius(m),K=j().innerRadius(m*P).outerRadius(m*P),S=v.append("g");S.append("circle").attr("cx",0).attr("cy",0).attr("r",m+k/2).attr("class","pieOuterCircle");const y=g.getSections(),Q=Mt(y),U=[l.pie1,l.pie2,l.pie3,l.pie4,l.pie5,l.pie6,l.pie7,l.pie8,l.pie9,l.pie10,l.pie11,l.pie12];let A=0;y.forEach(e=>{A+=e});const L=Q.filter(e=>(e.data.value/A*100).toFixed(0)!=="0"),M=mt(U).domain([...y.keys()]);S.selectAll("mySlices").data(L).enter().append("path").attr("d",J).attr("fill",e=>M(e.data.label)).attr("class",e=>{let i="pieCircle";return u.highlightSlice==="hover"?i+=" highlightedOnHover":u.highlightSlice===e.data.label&&(i+=" highlighted"),i}),S.selectAll("mySlices").data(L).enter().append("text").text(e=>(e.data.value/A*100).toFixed(0)+"%").attr("transform",e=>"translate("+K.centroid(e)+")").style("text-anchor","middle").attr("class","slice");const X=v.append("text").text(g.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText"),$=[...y.entries()].map(([e,i])=>({label:e,value:i})),f=v.selectAll(".legend").data($).enter().append("g").attr("class","legend");f.append("rect").attr("width",r).attr("height",r).style("fill",e=>M(e.label)).style("stroke",e=>M(e.label)),f.append("text").attr("x",r+o).attr("y",r-o).text(e=>g.getShowData()?`${e.label} [${e.value}]`:e.label);const x=Math.max(...f.selectAll("text").nodes().map(e=>e?.getBoundingClientRect().width??0));let C=b,O=w+F;const s=r+o,z=$.length*s;switch(G){case"center":f.attr("transform",(e,i)=>{const d=s*$.length/2,p=-x/2-(r+o),h=i*s-d;return"translate("+p+","+h+")"});break;case"top":C+=z,f.attr("transform",(e,i)=>{const d=m,p=-x/2-(r+o),h=i*s-d;return`translate(${p}, ${h})`}),S.attr("transform",()=>`translate(0, ${z+s})`);break;case"bottom":C+=z,f.attr("transform",(e,i)=>{const d=-m-s,p=-x/2-(r+o),h=i*s-d;return"translate("+p+","+h+")"});break;case"left":O+=r+o+x,f.attr("transform",(e,i)=>{const d=s*$.length/2,p=-m-(r+o),h=i*s-d;return"translate("+p+","+h+")"}),S.attr("transform",()=>`translate(${x+r+o}, 0)`);break;case"right":default:O+=r+o+x,f.attr("transform",(e,i)=>{const d=s*$.length/2,p=12*r,h=i*s-d;return"translate("+p+","+h+")"});break}const _=X.node()?.getBoundingClientRect().width??0,Y=w/2-_/2,Z=w/2+_/2,N=Math.min(0,Y),V=Math.max(O,Z)-N;T.attr("viewBox",`${N} 0 ${V} ${C}`),pt(T,C,V,u.useMaxWidth)},"draw"),zt={draw:Ot},Rt={parser:Tt,db:q,renderer:zt,styles:At};export{Rt as diagram};
