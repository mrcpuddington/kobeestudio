"""Run upstream checks with a local archive; never claim public delivery."""
import hashlib
import json
import pathlib
import shutil
import zipfile

import jsonschema
from validate import package

root = pathlib.Path(__file__).parent
repo = pathlib.Path('/Users/coreybusuttil/dev/github/kobeestudio')
draft = repo / 'pcm/build/official-submission'
identifier = 'com.github.mrcpuddington.kobeestudio'
metadata = draft / 'packages' / identifier / 'metadata.json'
previous = draft / 'upstream-metadata.json'
archive = repo / 'pcm/build/Kobee-Studio-1.5.20-pcm.zip'
current = json.loads(metadata.read_text())
upstream = json.loads(previous.read_text())
old_versions = {v['version']: v for v in upstream['versions']}
new_versions = {v['version']: v for v in current['versions']}
assert all(new_versions[key] == value for key, value in old_versions.items())
added = set(new_versions) - set(old_versions)
assert added == {'1.5.20'}, added
version = new_versions['1.5.20']
assert version['status'] == 'testing'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == version['download_sha256']

with zipfile.ZipFile(archive) as package_zip:
    embedded = json.loads(package_zip.read('metadata.json'))
    jsonschema.validate(embedded, json.loads((root / 'schema-v2.json').read_text()))
    assert not any(key.startswith('download_') for key in embedded['versions'][0])


def use_local_archive(url, target):
    assert url == version['download_url'], 'Unexpected URL in local-only validator'
    shutil.copyfile(archive, target)
    print('LOCAL ARCHIVE SUBSTITUTE: no public download verified')
    return True


package.download_file = use_local_archive
package.main([
    identifier, str(metadata), str(previous),
    '--schema-v2', str(root / 'schema-v2.json'),
    '--schema-v1', str(root / 'schema-v1.json'),
])
print('Existing upstream versions retained byte-for-value; embedded v2 metadata validated.')
print('Local candidate only. Public download, GitLab CI and temporary PCM install remain pending.')
