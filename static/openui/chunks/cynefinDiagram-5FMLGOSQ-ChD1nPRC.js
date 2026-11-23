import{p as $t}from"./chunk-JWPE2WC7-BQRyKMhJ.js";import{s as gt,g as ut,o as bt,n as wt,a as Ct,b as Dt,_ as i,l as V,D as kt,d as Bt,p as At,A as U,y as X,B as Tt,F as at}from"./mermaid.core-a7IuLF6e.js";import{p as St}from"./cynefin-OW5HDTMX-CamUxOHq.js";var rt=i(()=>({domains:new Map,transitions:[]}),"createDefaultData"),_=rt(),zt=i(()=>_.domains,"getDomains"),Mt=i(()=>_.transitions,"getTransitions"),vt=i(t=>{if(t)for(const e of t){const n=e.domain,a=(e.items??[]).map(c=>({label:c.label}));_.domains.set(n,{name:n,items:a})}},"setDomains"),Lt=i(t=>{t&&(_.transitions=t.filter(e=>e.from===e.to?(V.warn(`Cynefin: self-loop transition on domain "${e.from}" is not meaningful and will be skipped.`),!1):!0).map(e=>({from:e.from,to:e.to,label:e.label||void 0})))},"setTransitions"),Ft=i(()=>U({...Tt.cynefin,...X().cynefin}),"getConfig"),Pt=i(()=>{At(),_=rt()},"clear"),O={getDomains:zt,getTransitions:Mt,setDomains:vt,setTransitions:Lt,getConfig:Ft,clear:Pt,setAccTitle:Dt,getAccTitle:Ct,setDiagramTitle:wt,getDiagramTitle:bt,getAccDescription:ut,setAccDescription:gt},It=i(t=>{$t(t,O),O.setDomains(t.domains),O.setTransitions(t.transitions)},"populate"),Rt={parse:i(async t=>{const e=await St("cynefin",t);V.debug(e),It(e)},"parse")};function j(t){let e=t+1831565813|0;return e=Math.imul(e^e>>>15,e|1),e^=e+Math.imul(e^e>>>7,e|61),((e^e>>>14)>>>0)/4294967296}i(j,"seededRandom");function ot(t){let e=0;for(let n=0;n<t.length;n++){const a=t.charCodeAt(n);e=(e<<5)-e+a,e|=0}return e}i(ot,"hashString");function it(t,e){return typeof t=="number"&&Number.isFinite(t)&&t!==0?t:ot(e)}i(it,"resolveSeed");function st(t,e,n,a){const c=t/2,p=a??t*.015,D=7,I=e/D,d=[];for(let r=0;r<=D;r++){const m=j(n+r*17)*p*2-p;d.push({x:c+m,y:r*I})}let k=`M${d[0].x},${d[0].y}`;for(let r=0;r<d.length-1;r++){const m=d[r],s=d[r+1],f=(m.y+s.y)/2,b=r%2===0?1:-1,h=p*1.5*b*j(n+r*31+7),R=m.x+h,W=f,H=s.x-h;k+=` C${R},${W} ${H},${f} ${s.x},${s.y}`}return k}i(st,"generateFoldPath");function ct(t,e,n,a){const c=e/2,p=a??e*.015,D=7,I=t/D,d=[];for(let r=0;r<=D;r++){const m=j(n+r*23)*p*2-p;d.push({x:r*I,y:c+m})}let k=`M${d[0].x},${d[0].y}`;for(let r=0;r<d.length-1;r++){const m=d[r],s=d[r+1],f=(m.x+s.x)/2,b=r%2===0?1:-1,h=p*1.5*b*j(n+r*37+11),R=f,W=m.y+h,H=f,E=s.y-h;k+=` C${R},${W} ${H},${E} ${s.x},${s.y}`}return k}i(ct,"generateHorizontalBoundary");function lt(t,e){const n=t/2,a=e*.5,c=e,p=t*.03;return[`M${n},${a}`,`C${n+p},${a+(c-a)*.2}`,`${n-p*1.5},${a+(c-a)*.55}`,`${n+p*.5},${a+(c-a)*.75}`,`C${n-p},${a+(c-a)*.85}`,`${n+p*.3},${a+(c-a)*.95}`,`${n},${c}`].join(" ")}i(lt,"generateCliffPath");function dt(t,e,n,a){return[`M${t-n},${e}`,`A${n},${a} 0 1,1 ${t+n},${e}`,`A${n},${a} 0 1,1 ${t-n},${e}`,"Z"].join(" ")}i(dt,"generateConfusionPath");var ft={complex:{model:"Probe \u2192 Sense \u2192 Respond",practice:"Emergent Practices"},complicated:{model:"Sense \u2192 Analyse \u2192 Respond",practice:"Good Practices"},clear:{model:"Sense \u2192 Categorise \u2192 Respond",practice:"Best Practices"},chaotic:{model:"Act \u2192 Sense \u2192 Respond",practice:"Novel Practices"},confusion:{model:"",practice:"Disorder"}},Wt=i((t,e)=>{const n=t/2,a=e/2;return{complex:{cx:n/2,cy:a/2,x:0,y:0,w:n,h:a},complicated:{cx:n+n/2,cy:a/2,x:n,y:0,w:n,h:a},chaotic:{cx:n/2,cy:a+a/2,x:0,y:a,w:n,h:a},clear:{cx:n+n/2,cy:a+a/2,x:n,y:a,w:n,h:a},confusion:{cx:n,cy:a,x:n*.7,y:a*.7,w:n*.6,h:a*.6}}},"getDomainLayouts"),Ht=i(()=>{const t=at(),e=X();return U(t,e.themeVariables).cynefin},"getCynefinDomainColors"),Y=3,Et=i((t,e,n,a)=>{const c=a.db,p=c.getDomains(),D=c.getTransitions(),I=c.getDiagramTitle(),d=c.getAccTitle(),k=c.getAccDescription(),r=c.getConfig(),m=Ht();V.debug("Rendering Cynefin diagram");const s=r.width,f=r.height,b=r.padding,h=r.showDomainDescriptions,R=r.boundaryAmplitude,W=s+b*2,H=f+b*2,E={complex:m.complexBg,complicated:m.complicatedBg,clear:m.clearBg,chaotic:m.chaoticBg,confusion:m.confusionBg},B=kt(e);Bt(B,H,W,r.useMaxWidth??!0),B.attr("viewBox",`0 0 ${W} ${H}`),d&&B.append("title").text(d),k&&B.append("desc").text(k);const A=B.append("g").attr("transform",`translate(${b}, ${b})`),N=Wt(s,f),Z=it(r.seed,e),pt=A.append("g").attr("class","cynefin-backgrounds"),q=["complex","complicated","chaotic","clear"];for(const l of q){const o=N[l];pt.append("rect").attr("class","cynefinDomain").attr("x",o.x).attr("y",o.y).attr("width",o.w).attr("height",o.h).attr("fill",E[l]).attr("fill-opacity",.4).attr("stroke","none")}const Q=A.append("g").attr("class","cynefin-boundaries");Q.append("path").attr("class","cynefinBoundary").attr("d",st(s,f,Z,R)).attr("fill","none"),Q.append("path").attr("class","cynefinBoundary").attr("d",ct(s,f,Z+100,R)).attr("fill","none"),Q.append("path").attr("class","cynefinCliff").attr("d",lt(s,f)).attr("fill","none");const mt=s*.15,yt=f*.15;A.append("path").attr("class","cynefinConfusion").attr("d",dt(s/2,f/2,mt,yt)).attr("fill",E.confusion).attr("fill-opacity",.5);const J=A.append("g").attr("class","cynefin-labels");for(const l of q){const o=N[l];J.append("text").attr("class","cynefinDomainLabel").attr("x",o.cx).attr("y",h?o.cy-30:o.cy).attr("text-anchor","middle").attr("dominant-baseline","middle").text(l.charAt(0).toUpperCase()+l.slice(1))}if(J.append("text").attr("class","cynefinDomainLabel").attr("x",s/2).attr("y",h?f/2-10:f/2).attr("text-anchor","middle").attr("dominant-baseline","middle").text("Confusion"),h){const l=A.append("g").attr("class","cynefin-subtitles");for(const o of q){const x=N[o],y=ft[o];l.append("text").attr("class","cynefinSubtitle").attr("x",x.cx).attr("y",x.cy-10).attr("text-anchor","middle").attr("dominant-baseline","middle").text(y.model),l.append("text").attr("class","cynefinSubtitle").attr("x",x.cx).attr("y",x.cy+5).attr("text-anchor","middle").attr("dominant-baseline","middle").text(y.practice)}l.append("text").attr("class","cynefinSubtitle").attr("x",s/2).attr("y",f/2+8).attr("text-anchor","middle").attr("dominant-baseline","middle").text(ft.confusion.practice)}const K=A.append("g").attr("class","cynefin-items"),T=26,tt=10,xt=["complex","complicated","chaotic","clear","confusion"];for(const l of xt){const o=p.get(l);if(!o||o.items.length===0)continue;const x=N[l],y=l==="confusion";let v=o.items,L=0;y&&o.items.length>Y&&(L=o.items.length-Y,v=o.items.slice(0,Y));let S;if(y){const g=h?22:14;S=x.cy+g}else S=x.cy+(h?25:15);if([...v].forEach((g,z)=>{const w=S+z*(T+4),M=K.append("g"),F=M.append("text").attr("class","cynefinItemText").attr("x",0).attr("y",T/2).attr("text-anchor","middle").attr("dominant-baseline","central").text(g.label);let u=g.label.length*7;const $=F.node();if($&&typeof $.getBBox=="function"){const G=$.getBBox();G.width>0&&(u=G.width)}const C=u+tt*2,P=x.cx-C/2;M.attr("transform",`translate(${P}, ${w})`),M.insert("rect","text").attr("class","cynefinItem").attr("x",0).attr("y",0).attr("width",C).attr("height",T).attr("rx",4).attr("ry",4).attr("fill",E[l]).attr("fill-opacity",.95),F.attr("x",C/2).attr("y",T/2)}),L>0){const g=S+v.length*(T+4),z=`+${L} more`,w=K.append("g"),M=w.append("text").attr("class","cynefinItemText").attr("x",0).attr("y",T/2).attr("text-anchor","middle").attr("dominant-baseline","central").text(z);let F=z.length*7;const u=M.node();if(u&&typeof u.getBBox=="function"){const P=u.getBBox();P.width>0&&(F=P.width)}const $=F+tt*2,C=x.cx-$/2;w.attr("transform",`translate(${C}, ${g})`),w.insert("rect","text").attr("class","cynefinItemOverflow").attr("x",0).attr("y",0).attr("width",$).attr("height",T).attr("rx",4).attr("ry",4).attr("fill",E[l]).attr("fill-opacity",.6),M.attr("x",$/2).attr("y",T/2)}}if(D.length>0){const l=B.select("defs").empty()?B.append("defs"):B.select("defs"),o=`cynefin-arrow-${e}`;l.append("marker").attr("id",o).attr("viewBox","0 0 10 10").attr("refX",9).attr("refY",5).attr("markerWidth",6).attr("markerHeight",6).attr("orient","auto-start-reverse").append("path").attr("d","M 0 0 L 10 5 L 0 10 z").attr("class","cynefinArrowHead");const x=A.append("g").attr("class","cynefin-arrows");D.forEach(y=>{const v=N[y.from],L=N[y.to];if(!v||!L)return;if(y.from===y.to){V.warn(`Cynefin renderer: skipping self-loop on domain "${y.from}"`);return}const S=v.cx,g=v.cy,z=L.cx,w=L.cy,M=(S+z)/2,F=(g+w)/2,u=z-S,$=w-g,C=Math.sqrt(u*u+$*$),P=C*.15,G=-$/C,ht=u/C,et=M+G*P,nt=F+ht*P;x.append("path").attr("class","cynefinArrowLine").attr("d",`M${S},${g} Q${et},${nt} ${z},${w}`).attr("fill","none").attr("marker-end",`url(#${o})`),y.label&&x.append("text").attr("class","cynefinArrowLabel").attr("x",et).attr("y",nt-6).attr("text-anchor","middle").attr("dominant-baseline","auto").text(y.label)})}I&&A.append("text").attr("class","cynefinTitle").attr("x",s/2).attr("y",-b/2).attr("text-anchor","middle").attr("dominant-baseline","middle").text(I)},"draw"),Nt={draw:Et},_t=i(()=>{const t=at(),e=X();return U(t,e.themeVariables).cynefin},"getCynefinTheme"),jt=i(()=>{const t=_t();return`
	.cynefinDomain {
		stroke: none;
	}
	.cynefinDomainLabel {
		font-size: ${t.domainFontSize}px;
		font-weight: bold;
		fill: ${t.labelColor};
	}
	.cynefinSubtitle {
		font-size: ${t.itemFontSize-1}px;
		fill: ${t.textColor};
		font-style: italic;
	}
	.cynefinItem {
		fill-opacity: 0.95;
		stroke: ${t.boundaryColor};
		stroke-width: 1;
	}
	.cynefinItemText {
		font-size: ${t.itemFontSize}px;
		fill: ${t.textColor};
	}
	.cynefinItemOverflow {
		fill-opacity: 0.6;
		stroke: ${t.boundaryColor};
		stroke-width: 1;
		stroke-dasharray: 3 2;
	}
	.cynefinBoundary {
		stroke: ${t.boundaryColor};
		stroke-width: ${t.boundaryWidth};
		stroke-dasharray: 6 3;
	}
	.cynefinCliff {
		stroke: ${t.cliffColor};
		stroke-width: ${t.cliffWidth};
	}
	.cynefinConfusion {
		stroke: ${t.boundaryColor};
		stroke-width: 1.5;
		stroke-dasharray: 4 2;
	}
	.cynefinArrowLine {
		stroke: ${t.arrowColor};
		stroke-width: ${t.arrowWidth};
		fill: none;
	}
	.cynefinArrowHead {
		fill: ${t.arrowColor};
		stroke: none;
	}
	.cynefinArrowLabel {
		font-size: ${t.itemFontSize-1}px;
		fill: ${t.textColor};
	}
	.cynefinTitle {
		font-size: ${t.domainFontSize+2}px;
		font-weight: bold;
		fill: ${t.labelColor};
	}
	`},"styles"),Gt=jt,Vt={parser:Rt,db:O,renderer:Nt,styles:Gt};export{Vt as diagram};
