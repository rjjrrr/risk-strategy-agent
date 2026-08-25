import type {ReactNode} from 'react';
import {businessLabel,metricHelp,type BusinessLabel as LabelInfo} from '../i18n/businessLabels';

export function BusinessLabel({value,map,className=''}:{value:unknown;map?:Record<string,LabelInfo>;className?:string}){
  const raw=String(value??'').trim(),info=businessLabel(raw,map);
  return <span className={`business-label ${className}`.trim()} title={info.description||`技术原值：${raw||'EMPTY'}`}>
    <span>{info.label}</span>{raw&&<small className="technical-value">{raw}</small>}
  </span>;
}

export function MetricHelp({name,children}:{name:keyof typeof metricHelp;children?:ReactNode}){
  return <span className="metric-help" title={metricHelp[name]} aria-label={`${name}：${metricHelp[name]}`}>
    {children||name}<span aria-hidden="true">i</span>
  </span>;
}
