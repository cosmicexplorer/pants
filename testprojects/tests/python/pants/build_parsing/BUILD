# N.B. This is used by an integration test to validate global scope binding in BUILD-file parsing.

PREFIX = 'test'

def generate_name(name):
  return '{}-{}'.format(PREFIX, name)

target(
  name=generate_name('nested-variable-access-in-function-call')
)

####

# target(
#   name=<...>,
# )

# If we can ensure that everything is able to reference the original AST, we can formulate BUILD
# file rewriting as AST transformations. This makes them expressible in python code by definition?!!
# That means scripts to transform BUILD files can be kept in source control, provided via 3rdparty
# packages, etc!!!

# Consider the ASTTokens 3rdparty library or similar to support obtaining the original source text,
# as well as rewriting!

# What kind of interface makes this the easiest to do the things we'd want to do?
# I think that the answer to that will probably be arrived at by translating current use cases for
# buildozer into something derived at first pretty directly from the python AST!!

# Start thinking about how we might want to output this to consume from other cli tools in a usable
# way!
# Ideally, we:
# 1. have some simplified AST for BUILD file rewriters to manipulate (compared to the full python
#    AST)
# 2. make that AST be able to generate some useful xml or json or something
