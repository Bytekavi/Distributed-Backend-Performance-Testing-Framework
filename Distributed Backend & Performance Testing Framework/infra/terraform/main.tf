locals {
  common_tags = merge(
    {
      Project   = "distributed-performance-framework"
      ManagedBy = "terraform"
    },
    var.tags
  )
}

resource "aws_security_group" "worker" {
  name_prefix = "performance-worker-"
  description = "Egress-only security group for distributed load workers"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.ssh_key_name == null ? [] : [1]
    content {
      description = "Optional operator SSH"
      protocol    = "tcp"
      from_port   = 22
      to_port     = 22
      cidr_blocks = [var.ssh_cidr]
    }
  }

  egress {
    description = "Workers need the control plane, Redis, registry, and test targets"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_instance" "worker" {
  count                  = var.worker_count
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_ids[count.index % length(var.subnet_ids)]
  vpc_security_group_ids = [aws_security_group.worker.id]
  key_name               = var.ssh_key_name

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 16
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    worker_image   = var.worker_image
    redis_host     = var.redis_host
    redis_port     = var.redis_port
    redis_password = var.redis_password
    api_base_url   = var.api_base_url
    worker_threads = var.worker_threads
    node_id        = "aws-worker-${count.index}"
  })

  tags = merge(local.common_tags, { Name = "performance-worker-${count.index}" })
}

