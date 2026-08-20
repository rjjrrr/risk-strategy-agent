export function Metric({label,value,sub,tone=''}:{label:string;value:any;sub?:string;tone?:string}){return <div className={'metric-card '+tone}><span>{label}</span><b>{value??'—'}</b>{sub&&<small>{sub}</small>}</div>}
export function Tag({children}:{children:any}){return <span className={'tag tag-'+String(children).toLowerCase()}>{children}</span>}
export function Empty({title='尚未导入数据',text='上传 CSV / Excel 开始风险分析'}:{title?:string;text?:string}){return <div className="empty"><div className="empty-icon">∅</div><b>{title}</b><p>{text}</p></div>}
