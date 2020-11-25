#
# Copyright 2018-2020 Elyra Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import ast
import json
import logging
import os
import sys

from typing import Dict, Optional

"""Utility functions and classes used for metadata applications and classes."""

logging.basicConfig(level=logging.INFO, format='[%(levelname)1.1s %(asctime)s.%(msecs).03d] %(message)s')


class Option(object):
    """Represents the base option class.
    """
    cli_option = None
    name = None
    description = None
    default_value = None
    required = False
    value = None
    type = None  # Only used by SchemaProperty instances for now
    processed = False

    def __init__(self, cli_option, name=None, description=None, default_value=None, one_of=None,
                 required=False, type="string"):
        self.cli_option = cli_option
        self.name = name
        self.description = description
        self.default_value = default_value
        self.value = default_value
        self.one_of = one_of
        self.required = required
        self.type = type

    def set_value(self, value):
        if self.type == 'array' or self.type == 'object':
            self.value = ast.literal_eval(value)
        elif self.type == 'integer':
            self.value = int(value)
        elif self.type == 'number':
            if "." in value:
                self.value = float(value)
            else:
                self.value = int(value)
        elif self.type == 'boolean':
            if isinstance(value, bool):
                self.value = value
            elif str(value).lower() in ("true", "1"):
                self.value = True
            elif str(value).lower() in ("false", "0"):
                self.value = False
            else:
                self.value = value  # let it take its course
        elif self.type == 'null':
            if str(value) in ("null", "None"):
                self.value = None
            else:
                self.value = value
        else:
            self.value = value

    def print_help(self):
        if isinstance(self, CliOption):
            print("{option}=<{type}>".format(option=self.cli_option, type=self.type))
        else:
            print(self.cli_option)
        self.print_description()

    def print_description(self):
        print("\t{}".format(self.description))


class CliOption(Option):
    """Represents a command-line option."""
    def __init__(self, cli_option, **kwargs):
        super(CliOption, self).__init__(cli_option, **kwargs)


class Flag(Option):
    """Represents a command-line flag.  When present, the value used is `not default_value`."""
    def __init__(self, flag, **kwargs):
        super(Flag, self).__init__(flag, type="boolean", **kwargs)


class SchemaProperty(CliOption):
    """Represents the necessary information to handle a property from the schema.
       No validation is performed on corresponding instance values since the
       schema validation in the metadata service applies that.
       SchemaProperty instances are initialized from the corresponding property stanza
       from the schema
    """
    # Skip the following meta-properties when building the description.  We will already
    # have description and type and the others are difficult to display in a succinct manner.
    # Schema validation will still enforce these.
    skipped_meta_properties = ['description', 'type', 'items', 'additionalItems', 'properties'
                               'propertyNames', 'dependencies', 'examples', 'contains',
                               'additionalProperties', 'patternProperties']
    # Turn off the inclusion of meta-property information in the printed help messages  (Issue #837)
    print_meta_properties = False

    def __init__(self, name, schema_property):
        self.schema_property = schema_property
        cli_option = '--' + name
        type = schema_property.get('type')

        super(SchemaProperty, self).__init__(cli_option=cli_option, name=name,
                                             description=schema_property.get('description'),
                                             default_value=schema_property.get('default'),
                                             type=type)

    def print_description(self):

        additional_clause = ""
        if self.print_meta_properties:  # Only if enabled
            for meta_prop, value in self.schema_property.items():
                if meta_prop in self.skipped_meta_properties:
                    continue
                additional_clause = self._build_clause(additional_clause, meta_prop, value)

        print("\t{}{}".format(self.description, additional_clause))

    def _build_clause(self, additional_clause, meta_prop, value):
        if len(additional_clause) == 0:
            additional_clause = additional_clause + "; "
        else:
            additional_clause = additional_clause + ", "
        additional_clause = additional_clause + meta_prop + ": " + str(value)
        return additional_clause


class MetadataSchemaProperty(SchemaProperty):
    """Represents the property from the schema that resides in the Metadata stanza.
    """
    def __init__(self, name, schema_property):
        super(MetadataSchemaProperty, self).__init__(name, schema_property)


class AppBase(object):
    """Base class for application-level classes.  Provides logging, arguments handling,
       help methods, and anything common to its derived classes.
    """
    subcommands = {}
    description = None
    argv = []
    argv_mappings = {}  # Contains separation of argument name to value

    def __init__(self, **kwargs):
        self.argv = kwargs['argv']
        self._get_argv_mappings()
        self.log = logging.getLogger()  # setup logger so that metadata service logging is displayed

    def _get_argv_mappings(self):
        """Walk argv and build mapping from argument to value for later processing. """
        log_option = file_option = None
        for arg in self.argv:
            if '=' in arg:
                option, value = arg.split('=', 1)
            else:
                option, value = arg, None
            # Check for --debug or --log-level option.  if cound set, appropriate
            # log-level and skip.  Note this so we can alter self.argv after processing.
            if option == '--debug':
                log_option = arg
                logging.getLogger().setLevel(logging.DEBUG)
                continue
            elif option == '--log-level':
                log_option = arg
                logging.getLogger().setLevel(value)
                continue
            elif option == '--file':  # load file has JSON and build argv_mappings from its contents
                file_option = arg
                self.load_argv_mappings_from_file(value)
                continue

            self.argv_mappings[option] = value
        if log_option:
            self.argv.remove(log_option)
        if file_option:
            self.argv.remove(file_option)

    def load_argv_mappings_from_file(self, filename: str):
        """When --file=JSON_FILE is used, this will convert the keys and values
           into argv mappings so that it will behave as if they were on the command line.
        """
        # Check that file can be loaded as JSON.  If not, let it throw, let it throw, let it throw.
        with open(filename) as json_file:
            md_json = json.load(json_file)
        # We loaded, add mapping for --name based on filename
        self.argv_mappings['--name'] = os.path.basename(filename).split('.')[0]
        self.load_argv_mappings_from_json(md_json)

    def load_argv_mappings_from_json(self, json_data: dict, prefix: Optional[str] = None) -> None:
        for k, v in json_data.items():
            prefixed_name = None
            if k != 'metadata':
                prefixed_name = (prefix + '.' + k) if prefix else k
            if type(v) == dict:  # object-valued property, deal with sub-object
                return self.load_argv_mappings_from_json(v, prefixed_name)
            self.argv_mappings['--' + prefixed_name] = v  # object-valued properties will have dict as value for now

    def log_and_exit(self, msg=None, exit_status=1, display_help=False):
        if msg:
            print(msg)
        if display_help:
            print()
            self.print_help()
        self.exit(exit_status)

    def get_subcommand(self):
        """Checks argv[0] to see if it matches one of the expected subcommands. If so,
           that item is removed from argv and that subcommand tuple (class, description)
           is returned.  If no an expected subcommand is not found (None, None) is returned.
        """
        if len(self.argv) > 0:
            arg = self.argv[0]
            if arg in self.subcommands.keys():
                subcommand = self.subcommands.get(arg)
                self._remove_argv_entry(arg)
                return subcommand

            if arg in ['--help', '-h']:
                self.log_and_exit(display_help=True)
            else:
                print("Subcommand '{}' is invalid.".format(self.argv[0]))
        return None

    def exit_no_subcommand(self):
        print("No subcommand specified. Must specify one of: %s" % list(self.subcommands))
        print()
        self.print_description()
        self.print_subcommands()
        self.exit(1)

    @staticmethod
    def schema_to_options(schema, level: Optional[int] = 0, prefix: Optional[str] = None) -> Dict[str, SchemaProperty]:
        """Takes a JSON schema and builds a list of SchemaProperty instances corresponding to each
           property in the schema.  There are two sections of properties, one that includes
           schema_name and display_name and another within the metadata container - which
           will be separated by class type - SchemaProperty vs. MetadataSchemaProperty.

           Properties within the metadata container that are themselves object-valued, will
           trigger recursion with a construct of using a dotted prefix prior to the sub-object's
           property.  (e.g., extra-config.name)
        """
        options = {}
        if 'properties' in schema:
            properties = schema['properties']
            for k, v in properties.items():
                prefixed_name = (prefix + '.' + k) if prefix and prefix != 'metadata' else k
                if k == 'schema_name':  # already have this option, skip
                    continue
                if v['type'] == 'object':
                    options.update(AppBase.schema_to_options(properties[k], level + 1, prefixed_name))
                elif level == 0:  # Special handling for schema properties
                    options[prefixed_name] = SchemaProperty(prefixed_name, v)
                else:
                    options[prefixed_name] = MetadataSchemaProperty(prefixed_name, v)

            required_props = schema.get('required')
            if required_props:
                for required in required_props:
                    # skip schema_name & metadata, already required, and metadata is not an option to be presented
                    if required not in ['schema_name', 'metadata']:
                        prefixed_name = (prefix + '.' + required) if prefix and prefix != 'metadata' else required
                        options.get(prefixed_name).required = True
        else:  # object-value schema property doesn't define explicit properties, just add option
            options[prefix] = MetadataSchemaProperty(prefix, schema)
        return options

    def process_cli_option(self, cli_option, check_help=False):
        """Check if the given option exists in the current arguments.  If found set its
           the Option instance's value to that of the argv.  Once processed, update the
           argv lists by removing the option.  If the option is a required property and
           is not in the argv lists or does not have a value, exit.
        """
        # if check_help is enabled, check the arguments for help options and
        # exit if found. This is only necessary when processing invidual options.
        if check_help and self.has_help():
            self.log_and_exit(display_help=True)

        if cli_option.processed:
            return
        option = cli_option.cli_option
        if option in self.argv_mappings.keys():
            if isinstance(cli_option, Flag):  # flags set their value opposite their default
                cli_option.value = not cli_option.default_value
            else:  # this is a regular option, just set value
                cli_option.set_value(self.argv_mappings.get(option))
                if cli_option.required:
                    if not cli_option.value:
                        self.log_and_exit("Parameter '{}' requires a value.".
                                          format(cli_option.cli_option), display_help=True)
                    elif cli_option.one_of:  # ensure value is in set
                        if cli_option.value not in cli_option.one_of:
                            self.log_and_exit("Parameter '{}' requires one of the following values: {}".
                                              format(cli_option.cli_option, cli_option.one_of), display_help=True)
            self._remove_argv_entry(option)
        elif self.required_value_is_missing(cli_option):
            if cli_option.one_of is None:
                self.log_and_exit("'{}' is a required parameter.".
                                  format(cli_option.cli_option), display_help=True)
            else:
                self.log_and_exit("'{}' is a required parameter and must be one of the following values: {}.".
                                  format(cli_option.cli_option, cli_option.one_of), display_help=True)

        cli_option.processed = True

    def required_value_is_missing(self, option: Option) -> bool:
        """Checks is required-value option is missing a value.  This also takes into
           account required properties on sub-objects (dotted notation).  Only if all
           other options of the same sub-object do not have values will we skip enforcement.
        """
        if option.required and option.value is None:
            if '.' not in option.name:
                return True

            sub_option_prefix = option.cli_option.rsplit('.', 1)[0] + '.'
            # Check for option options on this sub-object, if any have values, return True
            for other_option, other_value in self.argv_mappings.items():
                if other_option.startswith(sub_option_prefix) and other_value is not None:
                    return True
            # Set the option to non-required, otherwise this will affect things downstream
            option.required = False
        return False

    def process_cli_options(self, cli_options):
        """For each Option instance in the list, process it according to the argv lists.
           After traversal, if arguments still remain, log help and exit.
        """
        # Since we're down to processing options (no subcommands), scan the arguments
        # for help entries and, if found, exit with the help message.
        if self.has_help():
            self.log_and_exit(display_help=True)

        for option in cli_options:
            self.process_cli_option(option)

        # Check if there are still unprocessed arguments.  If so, log and exit.
        if len(self.argv) > 0:
            msg = "The following arguments were unexpected: {}".format(self.argv)
            self.log_and_exit(msg, display_help=True)

    def has_help(self):
        """Checks the arguments to see if any match the help options.
           We do this by converting two lists to sets and checking if
           there's an intersection.
        """
        helps = {'--help', '-h'}
        args = set(self.argv_mappings.keys())
        help_list = list(helps & args)
        return len(help_list) > 0

    def _remove_argv_entry(self, cli_option):
        """Removes the argument entry corresponding to cli_option in both
           self.argv and self.argv_mappings
        """
        # build the argv entry from the mappings since it must be located with name=value
        if cli_option not in self.argv_mappings.keys():
            self.log_and_exit("Can't find option '{}' in argv!".format(cli_option))

        entry = cli_option
        value = self.argv_mappings.get(cli_option)
        if value:
            entry = entry + '=' + value
        if entry in self.argv:
            self.argv.remove(entry)
        self.argv_mappings.pop(cli_option)

    def print_help(self):
        self.print_description()

    def print_description(self):
        print(self.description)

    def print_subcommands(self):
        print()
        print("Subcommands")
        print("-----------")
        print("Subcommands are launched as `elyra-metadata cmd [args]`. For information on")
        print("using subcommand 'cmd', run: `elyra-metadata cmd -h`.")
        print()
        for subcommand, desc in self.subcommands.items():
            print(subcommand)
            print("    {}".format(desc[1]))

    def exit(self, status):
        sys.exit(status)
