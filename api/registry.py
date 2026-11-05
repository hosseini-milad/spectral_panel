"""Explicit routes; request fields derive from existing command parsers."""
import argparse
import hashlib
import json
import math
from copy import deepcopy
from functools import lru_cache

from django.core.management import get_commands,load_command_class
from django.core.management.base import CommandError
from rest_framework import serializers

# No arbitrary command name or shell text can be executed through HTTP.
ACTIONS = {
    'ingestion/ingest-parquet': 'ingest_parquet_directory',
    'ingestion/normalize-parquet': 'normalize_parquet_dataset',
    'ingestion/preview-normalization': 'preview_normalization',
    'ingestion/report': 'generate_ingest_report',
    'ingestion/reports': 'generate_ingest_reports',
    'layer1/build-candidates': 'build_clustered_candidates',
    'layer1/build-similarity-graph': 'build_candidate_similarity_graph',
    'layer1/build-representatives': 'build_day_representatives',
    'layer1/evaluate-representatives': 'evaluate_representatives',
    'layer1/visualize-representatives': 'visualize_representatives',
    'layer1/preview-representative-spread': 'preview_representative_spread',
    'layer1/evaluate-components': 'evaluate_graph_components',
    'layer1/verify-components': 'verify_graph_components',
    'layer1/evaluate-component-structure': 'evaluate_layer1_components',
    'layer1/evaluate-representative-allocation': 'evaluate_layer1_component_allocation',
    'layer1/audit-representative-inputs': 'audit_representative_inputs',
    'layer1/general-action': 'general-action',
    'layer1/hyper-general-action': 'hyper-general-action',
    'hierarchy/build': 'build_hierarchy_graph',
    'hierarchy/evaluate': 'evaluate_hierarchy_graph',
    'spectral/analyze': 'spectral_analysis',
    'spectral/message-passing': 'spectral_message_passing',
    'spectral/analyze-upper-hierarchy': 'analyze_upper_hierarchy',
    'learning/train-layer1-autoencoder': 'train_layer1_autoencoder',
    'learning/visualize-encoder-metas': 'visualize_encoder_metas',
    'behavior/learn-normal': 'learn_normal_behavior',
    'behavior/analyze-scores': 'analyze_behavior_scores',
    'behavior/evaluate-feature-graph-gap': 'evaluate_feature_graph_gap',
    'behavior/audit-representation': 'audit_behavior_representation',
    'behavior/train-neighborhood': 'train_neighborhood_representation',
    'behavior/build-signal-inputs': 'build_behavior_signal_inputs',
    'behavior/analyze-hierarchy': 'analyze_hierarchical_behavior',
    'behavior/prepare-normal-group-reference': 'prepare_normal_group_reference',
    'maintenance/reset-processed-day': 'reset_processed_day',
    'maintenance/cleanup-legacy': 'cleanup_legacy_collections',
    'legacy/build-initial-candidates': 'build_initial_candidates',
    'legacy/build-clustered-candidates-graph': 'build_clustered_candidates_graph',
    'legacy/build-representatives-directory': 'build_representatives_directory',
    'legacy/ingest-normalize-directory': 'ingest_normalize_directory',
    'legacy/normalize-directory': 'normalize_directory',
    'legacy/validate-model-input': 'validate_model_input',
}
BASE_OPTIONS = {'help','version','verbosity','settings','pythonpath','traceback','no_color','force_color','skip_checks'}


@lru_cache(maxsize=None)
def command_info(action):
    if action not in ACTIONS:
        raise ValueError('Unknown API action')
    name=ACTIONS[action]; commands=get_commands()
    command=load_command_class(commands[name],name)
    parser=command.create_parser('manage.py',name)
    fields={a.dest:a for a in parser._actions if a.option_strings and a.dest not in BASE_OPTIONS}
    metadata=[]
    for dest,a in fields.items():
        metadata.append(dict(name=dest,flags=a.option_strings,required=a.required,default=a.default,
            choices=list(a.choices) if a.choices is not None else None,nargs=a.nargs,
            type='boolean' if isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else getattr(a.type,'__name__','str'),
            help=str(a.help or '')))
    digest=hashlib.sha256(json.dumps(dict(command=name,parameters=metadata),sort_keys=True,default=str).encode()).hexdigest()
    return dict(command=name,parser=parser,fields=fields,parameters=metadata,schema_hash=digest,help=command.help)


def arguments(action,options):
    info=command_info(action);argv=[]
    for name,value in options.items():
        a=info['fields'][name]
        flag=next((x for x in a.option_strings if x.startswith('--')),a.option_strings[0])
        if not a.required and value==a.default:
            continue
        if isinstance(a,argparse._StoreTrueAction):
            if value:argv.append(flag)
        elif isinstance(a,argparse._StoreFalseAction):
            if not value:argv.append(flag)
        elif value is None:
            continue
        elif isinstance(value,list):
            if any(isinstance(v,str) and v.startswith('-') for v in value):
                raise serializers.ValidationError({name:'List strings cannot start with an option prefix.'})
            argv.extend([flag,*map(str,value)])
        else:
            argv.append(f'{flag}={value}')
    try:
        info['parser'].parse_args(argv)
    except (CommandError,SystemExit) as exc:
        raise serializers.ValidationError({'parameters':str(exc)}) from exc
    return argv


class StrictCommandSerializer(serializers.Serializer):
    action_key=None

    def to_internal_value(self,data):
        if not isinstance(data,dict):
            raise serializers.ValidationError('Expected a JSON object.')
        extra=set(data)-set(self.fields)
        if extra:
            raise serializers.ValidationError({key:'Unknown parameter.' for key in sorted(extra)})
        return super().to_internal_value(data)

    def validate(self,attrs):
        arguments(self.action_key,attrs)
        return attrs


class FiniteFloatField(serializers.FloatField):
    def to_internal_value(self,data):
        value=super().to_internal_value(data)
        if not math.isfinite(value):raise serializers.ValidationError('A finite number is required.')
        return value


def _field(a):
    kwargs=dict(required=a.required,help_text=str(a.help or ''))
    if not a.required and a.default is not argparse.SUPPRESS:
        kwargs['default']=deepcopy(a.default)
    boolean=isinstance(a,(argparse._StoreTrueAction,argparse._StoreFalseAction))
    if boolean:return serializers.BooleanField(**kwargs)
    kwargs['allow_null']=a.default is None and not a.required
    if a.choices is not None:
        child=serializers.ChoiceField(choices=list(a.choices),**kwargs)
    elif a.type is int:
        child=serializers.IntegerField(min_value=-(2**63),max_value=2**63-1,**kwargs)
    elif a.type is float:
        child=FiniteFloatField(**kwargs)
    else:
        child=serializers.CharField(allow_blank=True,trim_whitespace=False,**kwargs)
    if a.nargs in ('+','*') or isinstance(a.nargs,int):
        child.required=True;child.allow_null=False;child.default=serializers.empty
        list_kwargs=dict(required=a.required,allow_null=a.default is None and not a.required,help_text=str(a.help or ''))
        if not a.required:list_kwargs['default']=deepcopy(a.default)
        if a.nargs=='+':list_kwargs['allow_empty']=False
        if isinstance(a.nargs,int):list_kwargs.update(min_length=a.nargs,max_length=a.nargs)
        return serializers.ListField(child=child,**list_kwargs)
    return child


@lru_cache(maxsize=None)
def serializer_for(action):
    info=command_info(action)
    attrs={name:_field(a) for name,a in info['fields'].items()}
    attrs.update(action_key=action,__module__='api.registry')
    return type(''.join(part.title().replace('-','') for part in action.split('/'))+'Request',
                (StrictCommandSerializer,),attrs)
