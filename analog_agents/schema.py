"""JSON-schema helpers shared by all agents (strict objects, every property required)."""


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def array(items, max_items=None):
    schema = dict(type='array', items=items)
    if max_items is not None:
        schema['maxItems'] = max_items
    return schema


TEXT = {'type': 'string'}
BOOL = {'type': 'boolean'}


def enum(values):
    return {'type': 'string', 'enum': list(values)}
