import os

import zaza
import zaza.charm_lifecycle.utils
import zaza.charm_lifecycle.test
import tempest.cmd.main
import tempfile



class TempestTest():

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        charm_config = zaza.charm_lifecycle.utils.get_charm_config()
        config_dir = '.tempest'
        config_workspace_yaml = os.path.join(config_dir, 'workspace.yaml')
        workspace_name = 'workspace'
        workspace_dir = os.path.join(config_dir, workspace_name)
        workspace_etc_dir = os.path.join(workspace_dir, 'etc')
        workspace_etc_tempest = os.path.join(workspace_etc_dir, 'tempest.conf')
        tempest_options = ['run', '--config-file',
                           workspace_etc_tempest,
                           '--workspace-path', config_workspace_yaml,
                           '--workspace', workspace_name]
        for model_alias in zaza.model.get_juju_model_aliases().keys():
            tempest_test_key = model_alias
            if model_alias == zaza.charm_lifecycle.utils.DEFAULT_MODEL_ALIAS:
                tempest_test_key = 'default'
            config = charm_config['tests_options']['tempest'][tempest_test_key]
            if config.get('smoke'):
                tempest_options.extend(['--smoke'])
            if config.get('regex'):
                tempest_options.extend(
                    ['--regex',
                     ' '.join([reg for reg in config.get('regex')])])
            if config.get('black-regex'):
                tempest_options.extend(
                    ['--black-regex',
                     ' '.join([reg for reg in config.get('black-regex')])])
            with tempfile.TemporaryDirectory() as tmpdirname:
                if config.get('whitelist'):
                    white_file = os.path.join(tmpdirname, 'white.cfg')
                    with open(white_file, 'w') as f:
                        f.write('\n'.join(config.get('whitelist')))
                        f.write('\n')
                    tempest_options.extend(['--whitelist-file', white_file])
                if config.get('blacklist'):
                    black_file = os.path.join(tmpdirname, 'black.cfg')
                    with open(black_file, 'w') as f:
                        f.write('\n'.join(config.get('blacklist')))
                        f.write('\n')
                    tempest_options.extend(['--blacklist-file', black_file])
                print(tempest_options)
                the_app = tempest.cmd.main.Main()
                project_root = os.getcwd()
                _exec_tempest = the_app.run(tempest_options)
                os.chdir(project_root)
                if _exec_tempest != 0:
                    return False
        return True
