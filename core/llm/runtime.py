from __future__ import annotations
import json
from typing import Any
from pydantic import ValidationError
from .bindings import BindingStore,SessionSecretStore
from .exceptions import InvalidResponse,NoActiveBinding
from .provider import MockProvider,OpenAICompatibleProvider
from .prompts import PromptRegistry
from .schemas import STRUCTURED_SCHEMAS

DEFAULT_URLS={'OPENAI':'https://api.openai.com/v1','DEEPSEEK':'https://api.deepseek.com/v1','QWEN_OPENAI_COMPATIBLE':'https://dashscope.aliyuncs.com/compatible-mode/v1','ZHIPU_OPENAI_COMPATIBLE':'https://open.bigmodel.cn/api/paas/v4'}
class LLMRuntime:
    def __init__(self,bindings:BindingStore,prompts:PromptRegistry):self.bindings=bindings;self.prompts=prompts
    def _provider(self,binding):
        if binding['provider']=='MOCK':return MockProvider()
        secret=SessionSecretStore.get(binding.get('key_ref'))
        if not secret:raise NoActiveBinding(f"No API key available for key_ref {binding.get('key_ref') or '(missing)'}")
        return OpenAICompatibleProvider(binding.get('base_url') or DEFAULT_URLS.get(binding['provider'],''),secret,timeout=binding['timeout_seconds'])
    def resolve(self,binding_id=None,agent_type=None):
        agent_default=self.prompts.default_binding(agent_type) if agent_type and binding_id in (None,'AUTO_ROUTER') else None
        binding,reason=self.bindings.resolve(agent_default or binding_id)
        if agent_default:reason=f"Agent default binding for {agent_type}"
        return binding,self._provider(binding),reason
    def messages(self,agent_type,history,context=''):
        prompt=self.prompts.get(agent_type);system=prompt['system_prompt'];body=(f"AGENT_TYPE={agent_type}\n<data_context>\n{context}\n</data_context>\n" if context else f"AGENT_TYPE={agent_type}\n")
        return prompt,[{'role':'system','content':system}]+history[:-1]+[{'role':history[-1]['role'],'content':body+history[-1]['content']}]
    def chat(self,agent_type,history,binding_id=None,context=''):
        binding,provider,reason=self.resolve(binding_id,agent_type);prompt,messages=self.messages(agent_type,history,context)
        fallback_used=False
        try:result=provider.chat(messages,model=binding['model'],temperature=binding['temperature'],max_tokens=binding['max_tokens'])
        except Exception as primary_error:
            fallback_id=binding.get('fallback_binding_id')
            if not fallback_id:raise
            primary=binding;binding,provider,_=self.resolve(fallback_id,agent_type);result=provider.chat(messages,model=binding['model'],temperature=binding['temperature'],max_tokens=binding['max_tokens']);reason=f"Primary {primary['binding_id']} failed ({getattr(primary_error,'code','PROVIDER_ERROR')}); configured fallback {binding['binding_id']} used";fallback_used=True
        parsed=None;repair=False
        if agent_type in STRUCTURED_SCHEMAS:
            try:parsed=STRUCTURED_SCHEMAS[agent_type].model_validate(json.loads(result['content'])).model_dump()
            except (ValueError,ValidationError):
                repair=True;repair_messages=messages+[{'role':'assistant','content':result['content']},{'role':'user','content':'Repair the previous answer into valid JSON matching the required schema. Return JSON only.'}]
                repaired=provider.chat(repair_messages,model=binding['model'],temperature=0,max_tokens=binding['max_tokens']);result=repaired
                try:parsed=STRUCTURED_SCHEMAS[agent_type].model_validate(json.loads(result['content'])).model_dump()
                except (ValueError,ValidationError) as e:raise InvalidResponse('Structured response failed validation after one repair attempt') from e
        return {'binding':binding,'prompt':prompt,'router_decision_reason':reason,'result':result,'structured':parsed,'repair_attempted':repair,'fallback_used':fallback_used}
    def stream(self,agent_type,history,binding_id=None,context=''):
        if agent_type!='GENERAL_CHAT':
            result=self.chat(agent_type,history,binding_id,context);yield result['result']['content'],result;return
        binding,provider,reason=self.resolve(binding_id,agent_type);prompt,messages=self.messages(agent_type,history,context);meta={'binding':binding,'prompt':prompt,'router_decision_reason':reason,'result':{'execution_mode':'MOCK' if binding['provider']=='MOCK' else 'LLM','usage':{}}}
        for chunk in provider.stream_chat(messages,model=binding['model'],temperature=binding['temperature'],max_tokens=binding['max_tokens']):yield chunk,meta
    def test_connection(self,binding_id):
        binding=self.bindings.raw(binding_id);provider=self._provider(binding);return provider.test_connection(binding['model'])
