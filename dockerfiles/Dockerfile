FROM registry.access.redhat.com/ubi8/ubi:8.2 AS jsonnet-builder

ENV GOPATH=/go
ENV JSONNET_VERSION=v0.15.0
ENV JSONNET_BUNDLER_VERSION=v0.3.1
ENV VALET_LIBSONNET_VERSION=d2a774e73549a202f97982dd6982daccdde0035e

RUN dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm && \
    dnf install -y git make gcc gcc-c++ tar gzip unzip && \
    dnf clean all

RUN mkdir /jsonnet && \
    git clone https://github.com/google/jsonnet.git --depth 1 /jsonnet && \
    cd /jsonnet && \
    git checkout -b ${JSONNET_VERSION} && \
    make

RUN dnf install -y go && \
    mkdir -p /go && \
    chmod -R 777 /go && \
    GO111MODULE=on go get github.com/jsonnet-bundler/jsonnet-bundler/cmd/jb@${JSONNET_BUNDLER_VERSION}

WORKDIR /jsonnet-bundler
RUN /go/bin/jb init && \
    /go/bin/jb install https://github.com/app-sre/valet-libsonnet@${VALET_LIBSONNET_VERSION}

FROM registry.access.redhat.com/ubi8/ubi:8.2

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.14
ENV GIT_SECRETS_VERSION=1.3.0
ENV JSONNET_VENDOR_DIR=/opt/jsonnet-bundler/vendor

RUN dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm && \
    curl -L https://github.com/openshift/origin/releases/download/v3.11.0/openshift-origin-client-tools-v3.11.0-0cbc58b-linux-64bit.tar.gz | tar -xvz && \
    pushd openshift-origin-client* && \
    mv oc kubectl /usr/local/bin && \
    popd && \
    curl -L -o /etc/yum.repos.d/devel:kubic:libcontainers:stable.repo https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/CentOS_8/devel:kubic:libcontainers:stable.repo && \
    dnf install -y skopeo && \
    dnf install -y python3 python3-pip python3-devel git unzip gcc gcc-c++ openssh-clients openssl glibc-langpack-en && \
    python3 -m pip install --upgrade pip setuptools && \
    dnf clean all

RUN curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

RUN curl https://github.com/awslabs/git-secrets/archive/${GIT_SECRETS_VERSION}.tar.gz -L -o git-secrets.tar.gz && \
    tar -zvxf git-secrets.tar.gz git-secrets-${GIT_SECRETS_VERSION}/git-secrets && \
    mv git-secrets-${GIT_SECRETS_VERSION}/git-secrets /usr/local/bin/git-secrets && \
    rm -rf git-secrets*

COPY --from=jsonnet-builder /jsonnet/jsonnet /usr/local/bin/jsonnet
COPY --from=jsonnet-builder /jsonnet-bundler/vendor ${JSONNET_VENDOR_DIR}
RUN find ${JSONNET_VENDOR_DIR} -type d -exec chmod 0755 {} \;

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY utils utils
COPY templates templates
COPY setup.py .

RUN python3 setup.py install

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
