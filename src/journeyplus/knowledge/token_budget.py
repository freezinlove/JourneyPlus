"""Observed incremental usage calibration, explicitly an estimate, not a tokenizer."""
import math


class InputTokenBudget:
    def __init__(self,state,model,*,comparison_tokens=7000,focused_tokens=7000):
        previous=state.get('input_budget_calibration',{})
        if previous.get('model')!=model:previous={'model':model,'samples':0,'max_observed_tokens_per_byte':0}
        self.calibration=previous;state['input_budget_calibration']=previous
        self.limits={True:comparison_tokens,False:focused_tokens}
        if min(self.limits.values())<1000:raise ValueError('Input token target must be at least 1000')
        self.baseline=None

    @property
    def ratio(self):
        # The initial 1/3 byte ratio exceeds observed incremental ratios in the
        # real Chinese/JSON acceptance runs. Add 25% above any higher observation.
        return max(1/3,self.calibration['max_observed_tokens_per_byte']*1.25)

    def byte_limit(self,comparing,configured_bytes):
        return min(configured_bytes,max(3000,math.floor(self.limits[comparing]/self.ratio)))

    def describe(self,byte_count,comparing):
        return {'method':'observed_incremental_estimate','estimated_tool_tokens':math.ceil(byte_count*self.ratio),
                'target_tool_tokens':self.limits[comparing],'tokens_per_byte_estimate':self.ratio,
                'calibration_samples':self.calibration['samples'],'includes_system_and_schema':False}

    def observe(self,metrics):
        if not metrics or not isinstance(metrics.get('usage'),dict):return
        tokens=metrics['usage'].get('prompt_tokens');size=metrics.get('user_prompt_bytes')
        if type(tokens) is not int or type(size) is not int:return
        point=(metrics.get('system_prompt_bytes'),metrics.get('schema_bytes'),size,tokens)
        if self.baseline is None:self.baseline=point;return
        base=self.baseline;delta_bytes=size-base[2];delta_tokens=tokens-base[3]
        if point[:2]!=base[:2] or delta_bytes<1000 or delta_tokens<0:return
        ratio=delta_tokens/delta_bytes
        self.calibration['max_observed_tokens_per_byte']=max(self.calibration['max_observed_tokens_per_byte'],ratio)
        self.calibration['samples']+=1
