from __future__ import annotations
import json,time
from abc import ABC,abstractmethod
from typing import Any,Iterator
import httpx
from .exceptions import AuthError,ConnectionError,InvalidResponse,ModelNotFound,ProviderTimeout,RateLimitError,LLMError

class LLMProvider(ABC):
    @abstractmethod
    def chat(self,messages:list[dict],**kwargs)->dict:...
    @abstractmethod
    def stream_chat(self,messages:list[dict],**kwargs)->Iterator[str]:...
    def structured_chat(self,messages,**kwargs):return self.chat(messages,**kwargs)
    def list_models(self):return []
    def test_connection(self,model):
        started=time.perf_counter();r=self.chat([{'role':'user','content':'Respond with "OK".'}],model=model,max_tokens=5,temperature=0);return {'status':'CONNECTED','latency_ms':round((time.perf_counter()-started)*1000),'model':model,'response':r['content'][:20]}

class MockProvider(LLMProvider):
    def _response(self,messages,model='mock-v1',**kwargs):
        text=messages[-1]['content']; joined='\n'.join(x.get('content','') for x in messages)
        if model=='mock-auth-fail':raise AuthError('Mock authentication failed')
        if model=='mock-timeout':raise ProviderTimeout('Mock timeout')
        if model=='mock-rate-limit':raise RateLimitError('Mock rate limit')
        if '[MOCK_AUTH_FAIL]' in text:raise AuthError('Mock authentication failed')
        if '[MOCK_RATE_LIMIT]' in text:raise RateLimitError('Mock rate limit')
        if '[MOCK_TIMEOUT]' in text:raise ProviderTimeout('Mock timeout')
        if '[MOCK_INVALID_JSON]' in text:return '{invalid json'
        if 'AGENT_TYPE=ANALYSIS_AGENT' in joined:
            return json.dumps({'analysis_summary':'NEW-only deterministic context reviewed.','semantic_findings':[{'title':'Available rule evidence','finding_type':'RULE_SIGNAL','evidence':{'scope':'NEW'},'interpretation':'Rule evidence can support a reviewable hypothesis.','confidence':'HIGH','source_ids':[]}],'hypotheses':[{'title':'Recent activity intensity may indicate higher risk','risk_mechanism':'Concentrated recent activity may indicate credit-seeking pressure.','evidence':{'scope':'NEW'},'source_fields':['query_cnt_7d'],'expected_direction':'HIGHER_RISK_WHEN_HIGH','confidence':'MEDIUM','estimated_cost':'LOW'}],'feature_proposals':[{'feature_name':'query_cnt_7d_review','feature_type':'RAW','source_fields':['query_cnt_7d'],'formula':'query_cnt_7d','semantic_meaning':'Recent query intensity pending governance validation.','expected_direction':'HIGHER_RISK_WHEN_HIGH','evidence':{'scope':'NEW'},'confidence':'MEDIUM','status':'REVIEW'}],'warnings':[],'missing_information':['Experiment history may be unavailable.']},ensure_ascii=False)
        if 'SEMANTIC_ANALYSIS' in joined:return json.dumps({'field':'mock_field','business_meaning':'Mock field','semantic_role':'NORMAL_FEATURE','risk_domain':'APPLICATION_BEHAVIOR','possible_relations':[],'allowed_feature_ops':['RAW'],'forbidden_feature_ops':[],'confidence':'HIGH','reason':'Mock structured evidence'},ensure_ascii=False)
        if 'HYPOTHESIS' in joined:return json.dumps({'hypothesis':'Recent activity acceleration indicates risk','evidence':{'source':'mock'},'risk_mechanism':'accelerating queries','candidate_feature_ideas':[{'feature_name':'query_acceleration','feature_type':'RATIO','source_fields':['query_cnt_7d','query_cnt_90d'],'formula':'query_cnt_7d / max(query_cnt_90d, 1)'}],'expected_direction':'HIGHER_RISK_WHEN_HIGH','confidence':'HIGH','cost':'LOW'})
        if 'PLANNER' in joined:return json.dumps({'next_action':'FEATURE_ADD','selected_hypothesis':'H1','reason':'highest confidence','expected_gain':'OOT discrimination','confidence':'HIGH','cost':'LOW','requires_human':True})
        if 'DIAGNOSIS' in joined:return json.dumps({'diagnosis_type':'OVERFITTING','evidence':{'auc_gap':.12},'severity':'HIGH','confidence':'HIGH','recommended_action':'reduce complexity','rollback_target':'LAST_STABLE','requires_human':True})
        return 'MOCK: '+text.replace('<data_context>','').split('</data_context>')[-1].strip()
    def chat(self,messages,model='mock-v1',**kwargs):
        content=self._response(messages,model=model,**kwargs);return {'content':content,'usage':{'prompt_tokens':10,'completion_tokens':max(1,len(content)//4),'total_tokens':10+max(1,len(content)//4)},'model':model,'execution_mode':'MOCK'}
    def stream_chat(self,messages,model='mock-v1',**kwargs):
        content=self._response(messages,model=model,**kwargs)
        for i in range(0,len(content),8):yield content[i:i+8]

class OpenAICompatibleProvider(LLMProvider):
    def __init__(self,base_url,api_key,organization=None,timeout=30):self.base_url=base_url.rstrip('/');self.api_key=api_key;self.organization=organization;self.timeout=timeout
    def _headers(self):
        h={'Authorization':f'Bearer {self.api_key}','Content-Type':'application/json'}
        if self.organization:h['OpenAI-Organization']=self.organization
        return h
    def _raise(self,e):
        if isinstance(e,httpx.TimeoutException):raise ProviderTimeout('Provider request timed out') from e
        if isinstance(e,httpx.ConnectError):raise ConnectionError('Provider connection failed') from e
        if isinstance(e,httpx.HTTPStatusError):
            code=e.response.status_code
            if code in (401,403):raise AuthError('Provider rejected credentials') from e
            if code==429:raise RateLimitError('Provider rate limit exceeded') from e
            if code==404:raise ModelNotFound('Model or endpoint not found') from e
            raise LLMError(f'Provider HTTP {code}') from e
        raise e
    def chat(self,messages,model,temperature=.2,max_tokens=1200,response_format=None,**kwargs):
        payload={'model':model,'messages':messages,'temperature':temperature,'max_tokens':max_tokens}
        if response_format:payload['response_format']=response_format
        try:
            with httpx.Client(timeout=self.timeout) as c:r=c.post(f'{self.base_url}/chat/completions',headers=self._headers(),json=payload);r.raise_for_status();data=r.json()
            return {'content':data['choices'][0]['message']['content'],'usage':data.get('usage',{}),'model':data.get('model',model),'execution_mode':'LLM'}
        except (KeyError,ValueError) as e:raise InvalidResponse('Provider returned an invalid response') from e
        except Exception as e:self._raise(e)
    def stream_chat(self,messages,model,temperature=.2,max_tokens=1200,**kwargs):
        payload={'model':model,'messages':messages,'temperature':temperature,'max_tokens':max_tokens,'stream':True}
        try:
            with httpx.stream('POST',f'{self.base_url}/chat/completions',headers=self._headers(),json=payload,timeout=self.timeout) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith('data:'):continue
                    data=line[5:].strip()
                    if data=='[DONE]':break
                    try:chunk=json.loads(data)['choices'][0]['delta'].get('content','')
                    except Exception:continue
                    if chunk:yield chunk
        except Exception as e:self._raise(e)
    def list_models(self):
        try:
            with httpx.Client(timeout=self.timeout) as c:r=c.get(f'{self.base_url}/models',headers=self._headers());r.raise_for_status();return [x['id'] for x in r.json().get('data',[])]
        except Exception as e:self._raise(e)
