const state={assets:[],categories:{}};
const $=selector=>document.querySelector(selector);
const money=(value,currency)=>value==null?"-":new Intl.NumberFormat("pt-BR",{style:"currency",currency,maximumFractionDigits:2}).format(value);
const compactMoney=(value,currency)=>value==null?"-":new Intl.NumberFormat("pt-BR",{style:"currency",currency,notation:"compact",maximumFractionDigits:2}).format(value);
const date=value=>value?new Intl.DateTimeFormat("pt-BR").format(new Date(value+"T12:00:00")):"-";

async function api(url){const response=await fetch(url);const data=await response.json();if(!response.ok)throw new Error(data.error||"Falha ao carregar dados");return data}
function toast(message){const el=$("#toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2600)}
function parseDate(value){return new Date(value+"T12:00:00")}
function dateToISO(value){const date=new Date(value);return`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`}
function addDays(value,days){const next=new Date(value);next.setDate(next.getDate()+days);return next}
function daysBetween(start,end){return Math.ceil((parseDate(dateToISO(end))-parseDate(dateToISO(start)))/86400000)}
function median(values){if(!values.length)return 0;const sorted=[...values].sort((a,b)=>a-b);const middle=Math.floor(sorted.length/2);return sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2}

async function load(){const data=await api("/api/assets");state.assets=data.assets||[];state.categories=data.categories||{};render()}

function forecast(asset,options={}){
  const dates=(asset.dividends||[]).map(item=>item.ex_date).filter(Boolean).sort((a,b)=>a.localeCompare(b));
  const unique=[...new Set(dates)];
  if(unique.length<2)return null;
  const minGap=options.minGap||15;
  const maxGap=options.maxGap||180;
  const gaps=[];
  for(let index=1;index<unique.length;index++){
    const gap=daysBetween(parseDate(unique[index-1]),parseDate(unique[index]));
    if(gap>=minGap&&gap<=maxGap)gaps.push(gap);
  }
  if(!gaps.length)return null;
  const interval=Math.round(median(gaps));
  let next=parseDate(unique[unique.length-1]);
  const today=parseDate(dateToISO(new Date()));
  while(next<today)next=addDays(next,interval);
  const days=daysBetween(today,next);
  const samples=gaps.length;
  const confidence=samples>=6?"Alta":samples>=3?"Media":"Baixa";
  return{asset,lastDate:unique[unique.length-1],nextDate:dateToISO(next),days,interval,samples,confidence};
}

function render(){
  const fiis=state.assets.filter(asset=>asset.category==="fiis_brasileiros").map(asset=>forecast(asset,{minGap:20,maxGap:45})).filter(Boolean).sort(sortForecast);
  const stocks=state.assets.filter(asset=>asset.category==="acoes_brasileiras").map(asset=>forecast(asset,{minGap:15,maxGap:180})).filter(Boolean).sort(sortForecast);
  renderSummary(fiis,stocks);
  renderSection("fiiCalendar",fiis,"Nenhum FII com histórico suficiente para estimar a próxima data com.");
  renderSection("stockCalendar",stocks,"Nenhuma ação brasileira com histórico suficiente para estimar a próxima data com.",{showAll:true});
}

function sortForecast(a,b){return a.days-b.days||a.asset.ticker.localeCompare(b.asset.ticker)}
function visibleRows(rows){const near=rows.filter(item=>item.days<=30);return near.length?near:rows.slice(0,12)}

function renderSummary(fiis,stocks){
  const next=[...fiis,...stocks].sort(sortForecast)[0];
  const nextLabel=next?`${next.asset.ticker} em ${next.days===0?"hoje":`${next.days} dia${next.days===1?"":"s"}`}`:"Sem previsão";
  $("#calendarSummary").innerHTML=`<article><small>FIIs monitorados</small><strong>${fiis.length}</strong></article><article><small>Ações monitoradas</small><strong>${stocks.length}</strong></article><article><small>Próxima oportunidade</small><strong>${nextLabel}</strong></article>`;
}

function renderSection(prefix,rows,emptyMessage,options={}){
  const visible=options.showAll?rows:visibleRows(rows);
  $(`#${prefix}Count`).textContent=visible.length?`${visible.length} ativo${visible.length===1?"":"s"} em destaque`:"Sem histórico suficiente";
  $(`#${prefix}List`).innerHTML=visible.length?visible.map(calendarRow).join(""):`<div class="empty">${emptyMessage}</div>`;
}

function calendarRow(item){
  const urgent=item.days<=5?"urgent":item.days<=10?"soon":"";
  const currency=item.asset.currency||"BRL";
  return`<article class="calendar-row ${urgent}"><div class="calendar-asset"><span>${item.asset.ticker.slice(0,3)}</span><div><strong>${item.asset.ticker}</strong><small>${item.asset.segment||item.asset.name||"Sem segmento"}</small></div></div><div><small>Liquidez diária</small><strong>${compactMoney(item.asset.liquidity,currency)}</strong></div><div><small>Próxima data com estimada</small><strong>${date(item.nextDate)}</strong></div><div><small>Faltam</small><strong>${item.days===0?"Hoje":`${item.days} dia${item.days===1?"":"s"}`}</strong></div><div><small>Última data com</small><strong>${date(item.lastDate)}</strong></div><div><small>Padrão histórico</small><strong>${item.interval} dias</strong><small>Confiança ${item.confidence.toLowerCase()} · ${item.samples} intervalo${item.samples===1?"":"s"}</small></div><div><small>Cotação</small><strong>${money(item.asset.price,currency)}</strong></div></article>`;
}

load().catch(error=>toast(error.message));
