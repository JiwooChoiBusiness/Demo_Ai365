import{p as C}from"./chunk-JWPE2WC7-BQRyKMhJ.js";import{_ as f,A as w,D as v,d as P,l as m,b as z,a as S,n as F,o as W,g as D,s as E,y as T,B as A,p as Y}from"./mermaid.core-a7IuLF6e.js";import{p as H}from"./cynefin-OW5HDTMX-CamUxOHq.js";var L=A.packet,u,y=(u=class{constructor(){this.packet=[],this.setAccTitle=z,this.getAccTitle=S,this.setDiagramTitle=F,this.getDiagramTitle=W,this.getAccDescription=D,this.setAccDescription=E}getConfig(){const t=w({...L,...T().packet});return t.showBits&&(t.paddingY+=10),t}getPacket(){return this.packet}pushWord(t){t.length>0&&this.packet.push(t)}clear(){Y(),this.packet=[]}},f(u,"PacketDB"),u),M=1e4,R=f((t,e)=>{C(t,e);let r=-1,o=[],l=1;const{bitsPerRow:n}=e.getConfig();for(let{start:a,end:s,bits:c,label:d}of t.blocks){if(a!==void 0&&s!==void 0&&s<a)throw new Error(`Packet block ${a} - ${s} is invalid. End must be greater than start.`);if(a??(a=r+1),a!==r+1)throw new Error(`Packet block ${a} - ${s??a} is not contiguous. It should start from ${r+1}.`);if(c===0)throw new Error(`Packet block ${a} is invalid. Cannot have a zero bit field.`);for(s??(s=a+(c??1)-1),c??(c=s-a+1),r=s,m.debug(`Packet block ${a} - ${r} with label ${d}`);o.length<=n+1&&e.getPacket().length<M;){const[p,i]=j({start:a,end:s,bits:c,label:d},l,n);if(o.push(p),p.end+1===l*n&&(e.pushWord(o),o=[],l++),!i)break;({start:a,end:s,bits:c,label:d}=i)}}e.pushWord(o)},"populate"),j=f((t,e,r)=>{if(t.start===void 0)throw new Error("start should have been set during first phase");if(t.end===void 0)throw new Error("end should have been set during first phase");if(t.start>t.end)throw new Error(`Block start ${t.start} is greater than block end ${t.end}.`);if(t.end+1<=e*r)return[t,void 0];const o=e*r-1,l=e*r;return[{start:t.start,end:o,label:t.label,bits:o-t.start},{start:l,end:t.end,label:t.label,bits:t.end-l}]},"getNextFittingBlock"),x={parser:{yy:void 0},parse:f(async t=>{const e=await H("packet",t),r=x.parser?.yy;if(!(r instanceof y))throw new Error("parser.parser?.yy was not a PacketDB. This is due to a bug within Mermaid, please report this issue at https://github.com/mermaid-js/mermaid/issues.");m.debug(e),R(e,r)},"parse")},I=f((t,e,r,o)=>{const l=o.db,n=l.getConfig(),{rowHeight:a,paddingY:s,bitWidth:c,bitsPerRow:d}=n,p=l.getPacket(),i=l.getDiagramTitle(),h=a+s,b=h*(p.length+1)-(i?0:a),k=c*d+2,g=v(e);g.attr("viewBox",`0 0 ${k} ${b}`),P(g,b,k,n.useMaxWidth);for(const[$,B]of p.entries())N(g,B,$,n);g.append("text").text(i).attr("x",k/2).attr("y",b-h/2).attr("dominant-baseline","middle").attr("text-anchor","middle").attr("class","packetTitle")},"draw"),N=f((t,e,r,{rowHeight:o,paddingX:l,paddingY:n,bitWidth:a,bitsPerRow:s,showBits:c})=>{const d=t.append("g"),p=r*(o+n)+n;for(const i of e){const h=i.start%s*a+1,b=(i.end-i.start+1)*a-l;if(d.append("rect").attr("x",h).attr("y",p).attr("width",b).attr("height",o).attr("class","packetBlock"),d.append("text").attr("x",h+b/2).attr("y",p+o/2).attr("class","packetLabel").attr("dominant-baseline","middle").attr("text-anchor","middle").text(i.label),!c)continue;const k=i.end===i.start,g=p-2;d.append("text").attr("x",h+(k?b/2:0)).attr("y",g).attr("class","packetByte start").attr("dominant-baseline","auto").attr("text-anchor",k?"middle":"start").text(i.start),k||d.append("text").attr("x",h+b).attr("y",g).attr("class","packetByte end").attr("dominant-baseline","auto").attr("text-anchor","end").text(i.end)}},"drawWord"),_={draw:I},q={byteFontSize:"10px",startByteColor:"black",endByteColor:"black",labelColor:"black",labelFontSize:"12px",titleColor:"black",titleFontSize:"14px",blockStrokeColor:"black",blockStrokeWidth:"1",blockFillColor:"#efefef"},G=f(({packet:t}={})=>{const e=w(q,t);return`
	.packetByte {
		font-size: ${e.byteFontSize};
	}
	.packetByte.start {
		fill: ${e.startByteColor};
	}
	.packetByte.end {
		fill: ${e.endByteColor};
	}
	.packetLabel {
		fill: ${e.labelColor};
		font-size: ${e.labelFontSize};
	}
	.packetTitle {
		fill: ${e.titleColor};
		font-size: ${e.titleFontSize};
	}
	.packetBlock {
		stroke: ${e.blockStrokeColor};
		stroke-width: ${e.blockStrokeWidth};
		fill: ${e.blockFillColor};
	}
	`},"styles"),K={parser:x,get db(){return new y},renderer:_,styles:G};export{K as diagram};
