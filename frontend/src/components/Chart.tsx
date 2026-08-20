import ReactECharts from 'echarts-for-react';
export default function Chart({option,height=260}:{option:any;height?:number}){return <ReactECharts option={option} style={{height,width:'100%'}} opts={{renderer:'canvas'}}/>}
