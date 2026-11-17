"""Narrow chat-completions interface. No tool calls, fetching or implicit capability assumptions."""
import asyncio
import json
from typing import Protocol
import httpx

class ProviderError(Exception):
    def __init__(self,code,message):
        self.code,self.message=code,message
        self.usage=None
        self.attempts=0

class LLMProvider(Protocol):
    async def generate(self,messages:list[dict]) -> tuple[dict,dict|None,int]: ...

class CompatibleProvider:
    def __init__(self,settings,client): self.settings,self.client=settings,client
    async def generate(self,messages):
        s=self.settings
        payload={'model':s.llm_model,'messages':messages,'stream':False,'max_tokens':s.llm_max_output_tokens}
        if s.llm_json_mode: payload['response_format']={'type':'json_object'}
        code='AI_UNAVAILABLE'
        for attempt in range(s.llm_retries+1):
            usage=None
            try:
                response=await self.client.post(s.llm_base_url+'/chat/completions',json=payload,headers={'Authorization':f'Bearer {s.llm_api_key}'},timeout=s.llm_timeout_seconds)
                if response.status_code==429:
                    code='AI_RATE_LIMITED'
                    if attempt<s.llm_retries:
                        try: delay=min(3,max(0,float(response.headers.get('Retry-After','1'))))
                        except ValueError: delay=1
                        await asyncio.sleep(delay); continue
                    raise ProviderError(code,'AI 服务暂时限流，请稍后再试。')
                if response.status_code>=500:
                    code='AI_UPSTREAM_ERROR'
                    if attempt<s.llm_retries: await asyncio.sleep(0.2*(attempt+1)); continue
                if response.status_code>=400: raise ProviderError('AI_UPSTREAM_ERROR','AI 服务调用失败，请检查服务端模型与凭据配置。')
                data=response.json()
                if not isinstance(data,dict): raise ValueError('invalid envelope')
                raw_usage=data.get('usage')
                if isinstance(raw_usage,dict) and all(type(raw_usage.get(k)) is int and raw_usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
                    usage={'input_tokens':raw_usage['prompt_tokens'],'output_tokens':raw_usage['completion_tokens']}
                choice=data['choices'][0]
                if not isinstance(choice,dict) or not isinstance(choice.get('message'),dict): raise ValueError('invalid choice')
                if choice.get('finish_reason')=='length': raise ProviderError('AI_TRUNCATED','AI 输出被截断，未保存解释。')
                content=choice['message']['content']
                if not isinstance(content,str) or len(content)>100000: raise ValueError('invalid content')
                parsed=json.loads(content)
                if not isinstance(parsed,dict): raise ValueError('not object')
                return parsed,usage,attempt+1
            except ProviderError as exc:
                exc.usage,exc.attempts=usage,attempt+1
                raise
            except httpx.TimeoutException:
                code='AI_TIMEOUT'
                if attempt<s.llm_retries: await asyncio.sleep(0.2); continue
            except httpx.HTTPError:
                code='AI_CONNECTION'
                if attempt<s.llm_retries: await asyncio.sleep(0.2); continue
            except (KeyError,IndexError,TypeError,ValueError,json.JSONDecodeError):
                exc=ProviderError('AI_INVALID_OUTPUT','AI 返回内容不符合证据格式，未保存解释。')
                exc.usage,exc.attempts=usage,attempt+1
                raise exc
        exc=ProviderError(code,'AI 连接超时或不可用；原始资料仍可正常阅读。')
        exc.attempts=s.llm_retries+1
        raise exc
