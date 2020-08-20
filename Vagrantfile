Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/bionic64"
  config.ssh.forward_agent = true

  # Want to cd there because that directory is by default synced with
  # directory of this Vagrant file.
  # https://stackoverflow.com/questions/17864047
  config.ssh.extra_args = ["-t", "cd /vagrant; bash --login"]

  config.vm.provider "virtualbox" do |v|
    v.linked_clone = true
  end

  # TODO run scripts/install_18.04_deps.sh and test after
end
